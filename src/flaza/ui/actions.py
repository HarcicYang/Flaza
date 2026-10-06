"""UI 动作层：页面只调用这里，不直接触碰服务对象。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import webbrowser
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from flaza.config import AppConfig, ChatOpenPosition, LoginConfig, ThemeName, save_config
from flaza.core.events import GroupNameChanged
from flaza.core.models import (
    AtAllElement,
    AtElement,
    AudioElement,
    ChatTarget,
    FileElement,
    FriendChat,
    GroupChat,
    GroupMember,
    ImageElement,
    LoginPhase,
    Message,
    MessageElement,
    PendingRequest,
    QuoteElement,
    RequestKind,
    StoredMessage,
    TextElement,
    UserProfile,
    VideoElement,
    quote_preview_text,
)
from flaza.plugins.host import PluginSnapshot
from flaza.plugins.registry import PluginExtensionRegistry
from flaza.ui.state import CHAT_MESSAGE_PAGE_SIZE, UiStateStore

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

    @property
    def plugin_registry(self) -> PluginExtensionRegistry:
        return self._runtime.plugin_registry

    async def send_reaction(
        self,
        chat: ChatTarget,
        seq: int,
        emoji_id: str,
        emoji_type: int = 2,
        *,
        is_cancel: bool = False,
    ) -> None:
        """通过协议客户端发送或取消群消息表情回应。"""
        qq = self._runtime.qq
        if qq is None:
            raise RuntimeError("QQ 尚未启动，无法发送表情回应")
        await qq.send_reaction(chat, seq, emoji_id, emoji_type=emoji_type, is_cancel=is_cancel)

    async def send_nudge(self, target: ChatTarget, uin: int) -> None:
        """向好友或群成员发送戳一戳。"""
        qq = self._runtime.qq
        if qq is None:
            raise RuntimeError("QQ 尚未启动，无法发送戳一戳")
        await qq.send_nudge(target, uin)

    async def refresh_requests(self) -> None:
        """拉取服务端的待处理入群申请与邀请，合并进通知中心。"""
        qq = self._runtime.qq
        if qq is None:
            return
        try:
            requests = await qq.fetch_group_requests()
        except Exception:
            logger.exception("拉取群申请失败")
            return
        self._runtime.state.merge_requests(requests)

    async def respond_request(self, request: PendingRequest, accept: bool) -> None:
        """同意或拒绝一条好友申请/入群申请/群邀请。"""
        qq = self._runtime.qq
        if qq is None:
            raise RuntimeError("QQ 尚未启动，无法处理申请")
        if request.kind is RequestKind.FRIEND:
            if not request.target_uid:
                raise RuntimeError("好友申请缺少 uid")
            await qq.respond_friend_request(request.target_uid, accept)
        else:
            if not request.can_respond:
                raise RuntimeError("申请参数不完整，请刷新后重试")
            await qq.respond_group_request(request.group_id, request.seq, request.event_type, accept)
        self._runtime.state.resolve_request(request.key)

    async def fetch_user_profile(self, uid: str = "", uin: int = 0) -> UserProfile:
        """拉取好友或群成员资料卡。"""
        qq = self._runtime.qq
        if qq is None:
            raise RuntimeError("QQ 尚未启动，无法获取资料")
        return await qq.fetch_user_profile(uid, uin)

    async def like_friend(self, uid: str) -> int:
        """给好友名片点赞。"""
        qq = self._runtime.qq
        if qq is None:
            raise RuntimeError("QQ 尚未启动，无法点赞")
        return await qq.like_friend(uid)

    async def update_self_profile(self, nickname: str, bio: str) -> None:
        """修改当前账号昵称与个性签名，并同步本地投影。"""
        qq = self._require_qq()
        nickname = nickname.strip()
        bio = bio.strip()
        if nickname:
            await qq.set_self_nickname(nickname)
        await qq.set_self_bio(bio)
        info = self._runtime.state.self_info()
        if info is not None and nickname:
            self._runtime.state.self_info.set(info.model_copy(update={"nickname": nickname}))

    async def pick_avatar_file(self) -> str | None:
        """打开系统文件选择器选择头像图片。"""
        paths = await self._runtime.open_files(
            title="选择头像",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.webp *.bmp")],
        )
        return paths[0] if paths else None

    async def update_self_avatar(self, path: str) -> None:
        """上传并修改当前账号头像。"""
        await self._require_qq().set_self_avatar(path)

    async def list_group_members(self, group_id: int) -> list[GroupMember]:
        """读取本地群成员缓存，供 @ 提及等 UI 使用。"""
        return await self._runtime.storage.members.list_by_group(group_id)

    def _require_qq(self):
        qq = self._runtime.qq
        if qq is None:
            raise RuntimeError("QQ 尚未启动")
        return qq

    # ---- 群管理 ----

    async def rename_group(self, group_id: int, name: str) -> None:
        """修改群名，并立即把新名称投影到本地状态。"""
        await self._require_qq().rename_group(group_id, name)
        info = self._runtime.state.self_info()
        self._runtime.bus.publish(
            GroupNameChanged(
                group_id=group_id,
                name_new=name.strip(),
                operator_uid=info.uid if info else "",
            )
        )

    async def rename_group_member(self, group_id: int, uid: str, name: str) -> None:
        await self._require_qq().rename_group_member(group_id, uid, name)

    async def kick_group_member(self, group_id: int, uin: int) -> None:
        await self._require_qq().kick_group_member(group_id, uin)

    async def set_group_admin(self, group_id: int, uid: str, is_set: bool) -> None:
        await self._require_qq().set_group_admin(group_id, uid, is_set)

    async def set_group_special_title(self, group_id: int, uid: str, title: str) -> None:
        await self._require_qq().set_group_special_title(group_id, uid, title)

    async def set_group_mute(self, group_id: int, enable: bool) -> None:
        await self._require_qq().set_group_mute(group_id, enable)

    async def mute_group_member(self, group_id: int, uin: int, duration: int) -> None:
        await self._require_qq().mute_group_member(group_id, uin, duration)

    async def leave_group(self, group_id: int) -> None:
        await self._require_qq().leave_group(group_id)

    async def invite_group_members(self, group_id: int, uids: list[str] | dict[str, int]) -> None:
        await self._require_qq().invite_group_members(group_id, uids)

    async def set_group_essence(self, group_id: int, seq: int, rand: int, is_remove: bool = False) -> None:
        await self._require_qq().set_group_essence(group_id, seq, rand, is_remove)

    async def fetch_forward_messages(self, chat: ChatTarget, resid: str) -> list[Message]:
        """拉取合并转发内容。"""
        return await self._require_qq().fetch_forward_messages(chat, resid)

    async def forward_message(self, target: ChatTarget, message: Message) -> None:
        """把一条消息作为合并转发卡片发送到目标会话。"""
        await self._require_qq().forward_messages(target, [message])

    async def forward_messages(self, target: ChatTarget, messages: list[Message]) -> None:
        """把多条消息作为合并转发卡片发送到目标会话。"""
        await self._require_qq().forward_messages(target, messages)

    async def send_element(self, chat: ChatTarget, element: MessageElement) -> None:
        """把单个消息元素（表情等）复读到当前会话。"""
        await self._send_confirmed(chat, [element])

    async def send_element_to_active(self, element: MessageElement) -> None:
        """把单个消息元素发送到当前会话。"""
        chat = self._runtime.state.active_chat()
        if chat is None:
            return
        await self.send_element(chat, element)

    async def open_external(self, url: str) -> None:
        """用系统浏览器打开 http/https 链接。"""
        if not url.startswith(("http://", "https://")):
            return
        await asyncio.to_thread(webbrowser.open, url)

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
        with state.suppress_state_refresh():
            state.active_chat.set(chat)
            state.active_chat_title.set(self._chat_title(chat))

            snapshot = state.peek_chat_messages(chat)
            if snapshot is None:
                snapshot = await state.refresh_chat_messages(chat)
            stored = list(snapshot.messages)
            if isinstance(chat, GroupChat):
                await self._ensure_visible_group_roles(chat, stored)
            state.messages.set(snapshot.messages)
            state.has_older_messages.set(snapshot.has_older)
            message_service = self._message_service()
            if message_service is not None:
                message_service.schedule_media_cache([stored.message for stored in stored])
            await self._runtime.storage.messages.mark_all_read(chat)
            state.clear_chat_unread(chat)
        # 滚动策略由 HomePage 在会话打开流程末尾统一处理。
        await self.refresh_chat_view(force_scroll=False)

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
        await self._send_confirmed(chat, elements)
        await self._refresh_after_send_safely(chat, state)

    async def send_composed_blocks(self, blocks: Sequence[tuple[str, str]]) -> None:
        """按块顺序发送图文消息；块为 ``("text"|"image"|"at", value)``。

        ``"at"`` 块的 value 格式为 ``"uid:uin:display_name"``（提及成员）或 ``"__all__"``（@全体成员）。
        """
        state = self._runtime.state
        chat = state.active_chat()
        if chat is None:
            return

        elements = self._elements_from_blocks(blocks)
        if not elements:
            return
        await self._send_confirmed(chat, elements)
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
            msg=quote_preview_text(quoted.text, limit=200),
            sender_name=quoted.sender_name or str(quoted.sender_uin),
        )

        elements = [quote, *self._elements_from_blocks(blocks)]
        if not elements:
            return
        await self._send_confirmed(chat, elements)
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
        for path in paths:
            if not _looks_like_image(path):
                continue
            await self._send_confirmed(chat, [ImageElement(local_path=path)])
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
        for path in paths:
            await self._send_file_confirmed(chat, path)
            sent += 1

        if sent:
            await self._refresh_after_send_safely(chat, state)

    @staticmethod
    def is_image_path(path: str) -> bool:
        """判断路径是否属于受支持的图片文件。"""
        return _looks_like_image(path)

    async def _send_confirmed(self, chat: ChatTarget, elements: list[MessageElement]) -> None:
        """立即显示与成功态一致的乐观气泡，随后等待协议确认。

        成功后由 ``MessageSent`` 处理器在同一帧移除乐观气泡并投影真实消息，
        确认前后外观完全一致；失败时立即撤回气泡。
        """
        state = self._runtime.state
        pending = state.begin_outgoing_message(chat, elements)
        try:
            await self._message_service().send_message(chat, elements)
        except Exception:
            state.remove_pending_message(pending)
            raise

    async def _send_file_confirmed(self, chat: ChatTarget, path: str) -> None:
        """等待协议确认后写入本地文件消息。"""
        element = _outgoing_file_element(path)
        await self._send_confirmed(chat, [element])

    @staticmethod
    def _elements_from_blocks(blocks: Sequence[tuple[str, str]]) -> list[MessageElement]:
        """把 Composer 的块协议转换成领域消息元素。"""
        elements: list[MessageElement] = []
        for kind, value in blocks:
            if kind == "text":
                text = value.strip()
                if text:
                    elements.append(TextElement(text=text))
            elif kind == "image" and _looks_like_image(value):
                elements.append(ImageElement(local_path=value))
            elif kind == "at" and value == "__all__":
                elements.append(AtAllElement(text="@全体成员"))
            elif kind == "at" and ":" in value:
                parts = value.split(":", 2)
                uid = parts[0]
                try:
                    uin = int(parts[1])
                except (ValueError, IndexError):
                    uin = 0
                display_name = parts[2] if len(parts) > 2 else str(uin)
                elements.append(AtElement(uid=uid, uin=uin, text=f"@{display_name}"))
        return elements

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
        older = await self._runtime.storage.messages.list_before(chat, first_id, limit=CHAT_MESSAGE_PAGE_SIZE)
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
        client = self._runtime.media_cache.http_client
        await _download_to_path(client, file.file_url, destination)
        return destination

    async def _refresh_after_send_safely(self, chat: ChatTarget, state: UiStateStore) -> None:
        """发送已成功；刷新失败只记录日志，不把发送动作标记为失败。"""
        try:
            await self._refresh_after_send(chat, state)
        except Exception:
            logger.exception("发送后刷新聊天视图失败: chat=%s", chat.key)

    async def _refresh_after_send(self, chat: ChatTarget, state: UiStateStore) -> None:
        snapshot = await state.refresh_chat_messages(chat)
        state.messages.set(snapshot.messages)
        state.has_older_messages.set(snapshot.has_older)
        await self._runtime.storage.messages.mark_all_read(chat)
        state.clear_chat_unread(chat)
        await state.refresh_sessions()
        logger.info("发送消息后刷新聊天视图: chat=%s count=%s", chat.key, len(snapshot.messages))
        await self.refresh_chat_view(force_scroll=True)

    async def _refresh_chat_messages(self, chat: ChatTarget) -> None:
        """重新加载当前会话最近消息，不改变滚动位置。"""
        state = self._runtime.state
        snapshot = await state.refresh_chat_messages(chat)
        state.messages.set(snapshot.messages)
        state.has_older_messages.set(snapshot.has_older)
        await state.refresh_sessions()
        await self.refresh_chat_view(force_scroll=False)

    async def mark_chat_read(self, chat: ChatTarget) -> None:
        await self._runtime.storage.messages.mark_all_read(chat)
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

    async def save_theme(self, theme: ThemeName) -> None:
        """保存主题配置并立即应用，无需重启。"""
        window = self._runtime.config.window.model_copy(update={"theme": theme})
        config = self._runtime.config.model_copy(update={"window": window})
        save_config(config)
        self._runtime.config = config
        await self._runtime.set_theme(theme)

    async def save_chat_open_position(self, position: ChatOpenPosition) -> None:
        """保存打开会话时的滚动位置策略并立即生效。"""
        window = self._runtime.config.window.model_copy(update={"chat_open_position": position})
        config = self._runtime.config.model_copy(update={"window": window})
        save_config(config)
        self._runtime.config = config

    def save_login_config(self, login: LoginConfig) -> None:
        """保存登录配置并重启应用，让新配置在下一次启动时生效。"""
        config = self._runtime.config.model_copy(update={"login": login})
        save_config(config)
        _restart_app()

    # ---- 插件 ----

    def list_plugins(self) -> tuple[PluginSnapshot, ...]:
        """返回插件管理页需要的插件快照列表。"""
        return self._runtime.plugins.snapshot()

    async def reload_plugins(self) -> None:
        """按当前配置重新发现并加载全部启用的插件。"""
        await self._runtime.plugins.reload()

    async def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        """持久化插件启停状态并立即重载。"""
        await self._runtime.plugins.set_plugin_enabled(plugin_id, enabled)

    async def save_plugins_dir(self, plugins_dir: str) -> None:
        """保存插件目录并立即重载插件，无需重启应用。"""
        plugins_dir = plugins_dir.strip()
        if not plugins_dir:
            raise ValueError("插件目录不能为空")
        paths = self._runtime.config.paths.model_copy(update={"plugins_dir": plugins_dir})
        config = self._runtime.config.model_copy(update={"paths": paths})
        save_config(config)
        self._runtime.config = config
        await self._runtime.plugins.reload()

    async def pick_plugins_dir(self) -> str | None:
        """打开系统目录选择器；用户取消时返回 None。"""
        return await self._runtime.select_folder(
            title="选择插件目录",
            default_dir=self._runtime.config.paths.plugins_dir,
        )

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


async def _download_to_path(client: httpx.AsyncClient, url: str, destination: str) -> None:
    """把远程文件下载到指定路径；先写临时文件再替换，失败时不留下半个文件。"""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.flaza-download")

    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with temporary.open("wb") as file:
                async for chunk in response.aiter_bytes(1024 * 1024):
                    file.write(chunk)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise
    temporary.replace(target)


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
_AUDIO_SUFFIXES = {".amr", ".silk", ".mp3", ".m4a", ".wav", ".ogg"}


def _looks_like_image(path: str) -> bool:
    """按扩展名判断文件是否为受支持的图片。"""
    return Path(path).suffix.lower() in _IMAGE_SUFFIXES


def _outgoing_file_element(path: str) -> MessageElement:
    """按扩展名把本地文件映射为语音、视频或普通文件元素。"""
    name = Path(path).name
    suffix = Path(path).suffix.lower()
    if suffix in _AUDIO_SUFFIXES:
        return AudioElement(local_path=path, name=name)
    if suffix in _VIDEO_SUFFIXES:
        return VideoElement(local_path=path, name=name)
    return FileElement(file_name=name)
