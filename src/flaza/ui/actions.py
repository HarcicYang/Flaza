"""UI 动作层：页面只调用这里，不直接触碰服务对象。"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal

from flaza.config import AppConfig, LoginConfig, save_config
from flaza.core.models import ChatTarget, FriendChat, GroupChat, GroupMember, LoginPhase, StoredMessage

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from flaza.runtime import ApplicationRuntime


class UiActions:
    """集中承载登录、会话、消息和配置相关的用户动作。"""

    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime
        self._chat_view_refresher: Callable[[], Awaitable[None]] | None = None

    def set_chat_view_refresher(self, refresher: Callable[[], Awaitable[None]]) -> None:
        """由 HomePage 注册，确保状态变化后聊天 DOM 立即刷新。"""
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

    async def refresh_chat_view(self) -> None:
        if self._chat_view_refresher is not None:
            await self._chat_view_refresher()
        else:
            await self._runtime.render()

    async def send_message(self, text: str) -> None:
        state = self._runtime.state
        chat = state.active_chat()
        if chat is None or not text.strip():
            return

        await self._message_service().send_text(chat, text.strip())
        stored = await self._runtime.storage.messages.list_recent(chat)
        state.messages.set(tuple(stored))
        await self.mark_chat_read(chat)
        await state.refresh_sessions()
        logger.info("发送消息后刷新聊天视图: chat=%s count=%s", chat.key, len(stored))
        await self.refresh_chat_view()
        await self.scroll_chat_to_bottom(force=True)

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

    async def scroll_chat_to_bottom(self, *, force: bool = False) -> None:
        if force:
            script = (
                "(function () {"
                "  var el = document.querySelector('[data-neony-key=\"message-list\"]');"
                "  if (el) { el.scrollTop = el.scrollHeight; return 'forced'; }"
                "  return 'missing';"
                "})()"
            )
        else:
            script = (
                "(function () {"
                "  var el = document.querySelector('[data-neony-key=\"message-list\"]');"
                "  if (!el) return 'missing';"
                "  var distance = el.scrollHeight - el.scrollTop - el.clientHeight;"
                "  if (distance < 80) { el.scrollTop = el.scrollHeight; return 'bottom'; }"
                "  return 'keep:' + Math.round(distance);"
                "})()"
            )
        await self._runtime.eval_js(script)

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
