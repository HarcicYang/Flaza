"""UI 动作层：页面只调用这里，不直接触碰服务对象。"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from flaza.config import LoginConfig, save_config
from flaza.core.models import ChatTarget, FriendChat, GroupChat, LoginPhase

if TYPE_CHECKING:
    from flaza.runtime import ApplicationRuntime


class UiActions:
    """集中承载登录、会话、消息和配置相关的用户动作。"""

    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

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
        state.messages.set(tuple(stored))
        await self.mark_chat_read(chat)
        await state.refresh_sessions()
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
        await self._runtime.render()
        await self.scroll_chat_to_bottom()

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

    async def scroll_chat_to_bottom(self) -> None:
        script = (
            "(function () {"
            "  var el = document.querySelector('[data-neony-key=\"message-list\"]');"
            "  if (el) { el.scrollTop = el.scrollHeight; return 'ok'; }"
            "  return 'missing';"
            "})()"
        )
        await self._runtime.eval_js(script)

    # ---- 配置 ----

    def save_login_config(self, login: LoginConfig) -> None:
        """保存登录配置并重启应用，让新配置在下一次启动时生效。"""
        config = self._runtime.config.model_copy(update={"login": login})
        save_config(config)
        _restart_app()

    # ---- 内部方法 ----

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
