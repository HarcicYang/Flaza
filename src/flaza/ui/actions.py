"""UI 动作层：页面只调用这里，不直接触碰服务对象。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import urllib.request
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from flaza.config import AppConfig, LoginConfig, save_config
from flaza.core.models import (
    AtAllElement,
    AtElement,
    ChatTarget,
    FileElement,
    FriendChat,
    GroupChat,
    GroupMember,
    ImageElement,
    LoginPhase,
    MessageElement,
    QuoteElement,
    StoredMessage,
    TextElement,
)
from flaza.ui.state import UiStateStore

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from flaza.runtime import ApplicationRuntime


class UiActions:
    """集中承载登录、会话、消息和配置相关的用户动作。"""

    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime
        self._chat_view_refresher: Callable[[bool], Awaitable[None]] | None = None

    def set_chat_view_refresher(self, refresher: Callable[[bool], Awaitable[None]]) -> None:
        """由 HomePage 注册，确保状态变化后聊天 DOM 立即刷新。

        ``force_scroll=True`` 表示刷新后滚动到底部；历史消息加载等场景
        应传 False 以保持当前阅读位置。
        """
        self._chat_view_refresher = refresher

    # ---- 登录 ----

    async def start_qr_login(self) -> None:
        state = self._runtime.state
        try:
            await self._account_service().start_qr_login()
        except Exception as exc:
            state.login_phase.set(LoginPhase.FAILED)
            state.login_detail.set(str(exc))
            await self._runtime.render()

    # ---- 会话与消息 ----

    async def open_chat(self, chat: ChatTarget) -> None:
        state = self._runtime.state
        state.active_chat.set(chat)
        state.active_chat_title.set(self._chat_title(chat))

        stored = await self._runtime.storage.messages.list_recent(chat)
        if isinstance(chat, GroupChat):
            await self._ensure_visible_group_roles(chat, stored)
        state.messages.set(tuple(stored))
        state.has_older_messages.set(
            bool(stored) and await self._runtime.storage.messages.has_before(chat, stored[0].id)
        )
        message_service = self._message_service()
        if message_service is not None:
            message_service.schedule_media_cache([stored.message for stored in stored])
        await self.mark_chat_read(chat)
        await state.refresh_sessions()
        await self.refresh_chat_view()

    async def _ensure_visible_group_roles(self, chat: GroupChat, messages: list[StoredMessage]) -> None:
        known = self._runtime.state.group_roles()
        missing_uids: list[str] = []
        seen: set[str] = set()
        for stored in messages:
            message = stored.message
            if message.from_self or message.sender_uid in seen:
                continue
            seen.add(message.sender_uid)
            if f"{chat.group_id}:{message.sender_uid}" not in known:
                missing_uids.append(message.sender_uid)

        if not missing_uids:
            return
        members = await self._contact_service().ensure_member_roles(chat.group_id, missing_uids)
        self._merge_group_roles(members)

    async def refresh_chat_view(self, *, force_scroll: bool = True) -> None:
        if self._chat_view_refresher is not None:
            await self._chat_view_refresher(force_scroll)
        else:
            await self._runtime.render()

    async def send_message(self, text: str) -> None:
        """发送纯文本消息；供旧入口和测试使用。"""
        await self.send_composed_message(text, [])

    async def send_composed_message(self, text: str, image_paths: list[str]) -> None:
        """发送一条图文混排消息：文本 + 若干本地图片。"""
        state = self._runtime.state
        chat = state.active_chat()
        clean_text = text.strip()
        if chat is None or (not clean_text and not image_paths):
            return

        elements: list[MessageElement] = []
        if clean_text:
            elements.append(TextElement(text=clean_text))
        elements.extend(ImageElement(local_path=path) for path in image_paths if _looks_like_image(path))

        if not elements:
            return
        await self._message_service().send_message(chat, elements)
        await self._refresh_after_send_safely(chat, state)

    async def send_composed_blocks(self, blocks: Sequence[tuple[str, str]]) -> None:
        """按块顺序发送图文消息；块为 ``("text"|"image"|"at", value)``。

        ``"at"`` 块的 value 格式为 ``"uid:uin:display_name"``（提及成员）或 ``"__all__"``（@全体成员）。
        """
        state = self._runtime.state
        chat = state.active_chat()
        if chat is None:
            return

        elements: list[MessageElement] = []
        for kind, value in blocks:
            if kind == "text":
                text = value.strip()
                if text:
                    elements.append(TextElement(text=text))
            elif kind == "image":
                if _looks_like_image(value):
                    elements.append(ImageElement(local_path=value))
            elif kind == "at":
                if value == "__all__":
                    elements.append(AtAllElement(text="@全体成员"))
                elif ":" in value:
                    parts = value.split(":", 2)
                    uid = parts[0]
                    try:
                        uin = int(parts[1])
                    except (ValueError, IndexError):
                        uin = 0
                    display_name = parts[2] if len(parts) > 2 else str(uin)
                    elements.append(AtElement(uid=uid, uin=uin, text=f"@{display_name}"))

        if not elements:
            return
        await self._message_service().send_message(chat, elements)
        await self._refresh_after_send_safely(chat, state)

    async def send_reply_message(self, reply_to: StoredMessage, blocks: Sequence[tuple[str, str]]) -> None:
        """发送一条回复消息，在 blocks 之前插入 QuoteElement。"""
        state = self._runtime.state
        chat = state.active_chat()
        if chat is None:
            return

        quoted = reply_to.message
        quote = QuoteElement(
            seq=quoted.seq,
            uin=quoted.sender_uin,
            timestamp=quoted.timestamp,
            uid=quoted.sender_uid,
            msg=quoted.text[:200],
        )

        elements: list[MessageElement] = [quote]
        for kind, value in blocks:
            if kind == "text":
                text = value.strip()
                if text:
                    elements.append(TextElement(text=text))
            elif kind == "image":
                if _looks_like_image(value):
                    elements.append(ImageElement(local_path=value))
            elif kind == "at":
                if value == "__all__":
                    elements.append(AtAllElement(text="@全体成员"))
                elif ":" in value:
                    parts = value.split(":", 2)
                    uid = parts[0]
                    try:
                        uin = int(parts[1])
                    except (ValueError, IndexError):
                        uin = 0
                    display_name = parts[2] if len(parts) > 2 else str(uin)
                    elements.append(AtElement(uid=uid, uin=uin, text=f"@{display_name}"))

        if not elements:
            return
        await self._message_service().send_message(chat, elements)
        await self._refresh_after_send_safely(chat, state)

    async def pick_images(self) -> list[str]:
        """打开系统文件选择器选择图片，不发送，返回路径列表。"""
        if self._runtime.state.active_chat() is None:
            return []
        return await self._runtime.open_files(
            title="选择要发送的图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.webp *.bmp")],
        )

    async def pick_and_send_images(self) -> None:
        """打开系统文件选择器并发送选中的本地图片。"""
        if self._runtime.state.active_chat() is None:
            return
        paths = await self.pick_images()
        if not paths:
            return
        await self.send_images(paths)

    async def send_images(self, paths: list[str]) -> None:
        """顺序发送一组本地图片，全部完成后统一刷新聊天视图。"""
        state = self._runtime.state
        chat = state.active_chat()
        if chat is None:
            return

        sent = 0
        service = self._message_service()
        for path in paths:
            if not _looks_like_image(path):
                continue
            await service.send_image(chat, path)
            sent += 1

        if sent:
            await self._refresh_after_send_safely(chat, state)

    async def pick_and_send_files(self) -> None:
        """打开系统文件选择器并发送选中的本地文件。"""
        if self._runtime.state.active_chat() is None:
            return
        paths = await self._runtime.open_files(
            title="选择要发送的文件",
            filetypes=[("所有文件", "*.*")],
        )
        if not paths:
            return
        await self.send_files(paths)

    async def send_files(self, paths: list[str]) -> None:
        """顺序发送一组本地文件，全部完成后统一刷新聊天视图。"""
        state = self._runtime.state
        chat = state.active_chat()
        if chat is None:
            return

        sent = 0
        service = self._message_service()
        for path in paths:
            await service.send_file(chat, path)
            sent += 1

        if sent:
            await self._refresh_after_send_safely(chat, state)

    @staticmethod
    def is_image_path(path: str) -> bool:
        """判断路径是否属于受支持的图片文件。"""
        return _looks_like_image(path)

    async def load_older_messages(self) -> None:
        """加载当前会话更早的一页消息。

        更早消息通过 ``MessageList`` 的增量前置路径插入 DOM，不执行任何
        JavaScript；浏览器原生滚动锚定会尽量保持当前阅读位置。
        """
        state = self._runtime.state
        chat = state.active_chat()
        current = state.messages()
        if chat is None or not current:
            return

        first_id = current[0].id
        older = await self._runtime.storage.messages.list_before(chat, first_id)
        if not older:
            state.has_older_messages.set(False)
            await self.refresh_chat_view(force_scroll=False)
            return

        state.messages.set(tuple([*older, *current]))
        state.has_older_messages.set(await self._runtime.storage.messages.has_before(chat, older[0].id))
        await self.refresh_chat_view(force_scroll=False)

    async def recall_message(self, chat: ChatTarget, seq: int) -> None:
        """撤回自己发送的消息并刷新当前聊天流。"""
        await self._message_service().recall_message(chat, seq)
        await self._refresh_chat_messages(chat)

    async def copy_text(self, text: str) -> None:
        """把文本写入系统剪贴板。"""
        if text:
            await self._runtime.clipboard_write(text)

    async def read_clipboard(self) -> bytes | str:
        """读取系统剪贴板，供输入框粘贴图片使用。"""
        return await self._runtime.clipboard_read()

    async def download_file(self, file: FileElement) -> str | None:
        """弹出保存对话框并下载文件；返回保存路径，取消时返回 None。"""
        if not file.file_url:
            raise RuntimeError("该文件暂无下载链接")
        destination = await self._runtime.save_file(
            title="保存文件",
            default_name=file.file_name,
            filetypes=[("所有文件", "*.*")],
        )
        if destination is None:
            return None
        await asyncio.to_thread(_download_to_path, file.file_url, destination)
        return destination

    async def _refresh_after_send_safely(self, chat: ChatTarget, state: UiStateStore) -> None:
        """发送已成功；刷新失败只记录日志，不把发送动作标记为失败。"""
        try:
            await self._refresh_after_send(chat, state)
        except Exception:
            logger.exception("发送后刷新聊天视图失败: chat=%s", chat.key)

    async def _refresh_after_send(self, chat: ChatTarget, state: UiStateStore) -> None:
        stored = await self._runtime.storage.messages.list_recent(chat)
        state.messages.set(tuple(stored))
        state.has_older_messages.set(
            bool(stored) and await self._runtime.storage.messages.has_before(chat, stored[0].id)
        )
        await self.mark_chat_read(chat)
        await state.refresh_sessions()
        logger.info("发送消息后刷新聊天视图: chat=%s count=%s", chat.key, len(stored))
        await self.refresh_chat_view(force_scroll=True)

    async def _refresh_chat_messages(self, chat: ChatTarget) -> None:
        """重新加载当前会话最近消息，不改变滚动位置。"""
        state = self._runtime.state
        stored = await self._runtime.storage.messages.list_recent(chat)
        state.messages.set(tuple(stored))
        state.has_older_messages.set(
            bool(stored) and await self._runtime.storage.messages.has_before(chat, stored[0].id)
        )
        await state.refresh_sessions()
        await self.refresh_chat_view(force_scroll=False)

    async def mark_chat_read(self, chat: ChatTarget) -> None:
        latest_id = await self._runtime.storage.messages.latest_id(chat)
        if latest_id is not None:
            await self._runtime.storage.messages.mark_read(chat, latest_id)
            await self._runtime.state.refresh_sessions()

    async def refresh_sessions(self) -> None:
        await self._runtime.state.refresh_sessions()
        await self._runtime.render()

    async def sync_contacts(self) -> None:
        await self._contact_service().sync()

    # ---- 配置 ----

    def current_config(self) -> AppConfig:
        """返回运行时最新的配置，避免页面持有启动时的旧快照。"""
        return self._runtime.config

    async def save_theme(self, theme: Literal["dark", "light", "deep_blue"]) -> None:
        """保存主题配置并立即应用，无需重启。"""
        window = self._runtime.config.window.model_copy(update={"theme": theme})
        config = self._runtime.config.model_copy(update={"window": window})
        save_config(config)
        self._runtime.config = config
        await self._runtime.set_theme(theme)
        await self._runtime.render()

    def save_login_config(self, login: LoginConfig) -> None:
        """保存登录配置并重启应用，让新配置在下一次启动时生效。"""
        config = self._runtime.config.model_copy(update={"login": login})
        save_config(config)
        _restart_app()

    # ---- 内部方法 ----

    def _merge_group_roles(self, members: list[GroupMember]) -> None:
        if not members:
            return
        roles = dict(self._runtime.state.group_roles())
        for member in members:
            roles[f"{member.group_id}:{member.uid}"] = member.role
        self._runtime.state.group_roles.set(roles)

    def _chat_title(self, chat: ChatTarget) -> str:
        state = self._runtime.state
        if isinstance(chat, FriendChat):
            for friend in state.friends():
                if friend.uid == chat.uid:
                    return friend.display_name
            return str(chat.uin)
        if isinstance(chat, GroupChat):
            for group in state.groups():
                if group.group_id == chat.group_id:
                    return group.display_name
            return str(chat.group_id)
        return chat.key

    def _account_service(self):
        service = self._runtime.account_service
        if service is None:
            raise RuntimeError("账号服务尚未启动")
        return service

    def _message_service(self):
        service = self._runtime.message_service
        if service is None:
            raise RuntimeError("消息服务尚未启动")
        return service

    def _contact_service(self):
        service = self._runtime.contact_service
        if service is None:
            raise RuntimeError("联系人服务尚未启动")
        return service


def _restart_app() -> None:
    """使用当前 Python 解释器重新启动 Flaza。"""
    python = sys.executable
    os.execv(python, [python, "-m", "flaza"])


def _download_to_path(url: str, destination: str) -> None:
    """把远程文件下载到指定路径；先写临时文件再替换，失败时不留下半个文件。"""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.flaza-download")

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Flaza/0.1"})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as file:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                file.write(chunk)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise
    temporary.replace(target)


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _looks_like_image(path: str) -> bool:
    """按扩展名判断文件是否为受支持的图片。"""
    return Path(path).suffix.lower() in _IMAGE_SUFFIXES
