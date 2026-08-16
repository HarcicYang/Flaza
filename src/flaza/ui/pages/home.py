"""主窗口页面。"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from neony.application.elements import Progress, Text
from neony.dom import Div, DOMElement, Styles
from neony.dom.reactive import effect

from flaza.config import AppConfig
from flaza.core.events import (
    EventBus,
)
from flaza.core.models import ChatTarget
from flaza.ui.actions import UiActions
from flaza.ui.components.composer import Composer
from flaza.ui.components.image_viewer import ImageViewer
from flaza.ui.components.message_list import MessageList
from flaza.ui.components.new_chat_dialog import NewChatDialog
from flaza.ui.components.session_list import SessionList
from flaza.ui.components.settings_dialog import SettingsDialog
from flaza.ui.state import UiStateStore

_BODY = Styles(display="flex", flex_grow="1", min_height="0", width="100%")

_RIGHT = Styles(display="flex", flex_direction="column", flex_grow="1", min_width="0", min_height="0")

_CHAT_HEADER = Styles(
    display="flex",
    align_items="center",
    gap="8px",
    padding="10px 16px",
    border_bottom="1px solid var(--color-border)",
    flex_shrink="0",
)


class HomePage:
    """登录成功后的主界面。"""

    def __init__(
        self,
        state: UiStateStore,
        actions: UiActions,
        bus: EventBus,
        config: AppConfig,
        render: Callable[[], Awaitable[None]],
    ) -> None:
        self._state = state
        self._actions = actions
        self._config = config
        self._render = render
        self._settings_el: DOMElement | None = None
        self._new_chat: NewChatDialog | None = None
        self._new_chat_el: DOMElement | None = None
        self._state_refresh_task: asyncio.Task[None] | None = None
        self._state_refresh_again = False
        self._state_force_scroll = False
        self._bus = bus
        actions.set_chat_view_refresher(self._refresh_async)

        self.session_list = SessionList(state, actions, self._on_session_selected)
        self.image_viewer = ImageViewer(render)
        self.message_list = MessageList(state, self.image_viewer.open)
        self.composer = Composer(actions, render)

        chat_title = Text("", size="16px", weight="600")
        chat_title.bind_text(state.active_chat_title)
        chat_header = Div(styles=_CHAT_HEADER, container=[chat_title.build()])

        sync_progress = Progress(indeterminate=True, label="正在同步离线消息…")
        sync_root = sync_progress.build()
        sync_root.bind_visible(state.sync_in_progress)

        right = Div(
            styles=_RIGHT,
            container=[chat_header, self.message_list.root, self.composer.root],
        )
        body = Div(styles=_BODY, container=[self.session_list.root, right])
        self.root = Div(
            styles=Styles(display="flex", flex_direction="column", width="100%", flex_grow="1", min_height="0"),
            container=[sync_root, body, self.image_viewer.root],
        )

        self._apply_state()
        # 真实依赖 effect：这里读取 Signal，信号变化时自动调度增量刷新。
        effect(self._on_state_signal_changed)

    # ---- 数据刷新 ----

    def _apply_state(self) -> None:
        sessions = list(self._state.sessions())
        self.session_list.set_sessions(sessions)
        active = self._state.active_chat()
        self.message_list.set_messages(active, self._state.messages(), self._state.notices())

    def _on_state_signal_changed(self) -> None:
        # 建立 Effect 依赖；真实变化会进入下面的合并调度。
        _ = (
            self._state.sessions(),
            self._state.active_chat(),
            self._state.messages(),
            self._state.notices(),
            self._state.group_roles(),
            self._state.self_info(),
        )
        self._schedule_state_refresh()

    def _schedule_state_refresh(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._state_refresh_task is None:
            task = loop.create_task(self._state_refresh_loop())
            self._state_refresh_task = task
            task.add_done_callback(self._state_refresh_done)
        else:
            self._state_refresh_again = True

    def _state_refresh_done(self, task: asyncio.Task[None]) -> None:
        self._state_refresh_task = None
        if self._state_refresh_again:
            self._state_refresh_again = False
            loop = asyncio.get_running_loop()
            new_task = loop.create_task(self._state_refresh_loop())
            self._state_refresh_task = new_task
            new_task.add_done_callback(self._state_refresh_done)

    async def _state_refresh_loop(self) -> None:
        self._apply_state()
        await self._render()
        force_scroll = self._state_force_scroll
        self._state_force_scroll = False
        await self._actions.scroll_chat_to_bottom(force=force_scroll)

    async def _refresh_async(self) -> None:
        self._apply_state()
        await self._render()
        await self._actions.scroll_chat_to_bottom(force=True)

    # ---- 标题栏动作入口 ----

    async def open_new_chat(self) -> None:
        if self._new_chat_el is not None:
            with contextlib.suppress(ValueError):
                self.root.container.remove(self._new_chat_el)
        dialog = NewChatDialog(self._state, self._select_chat)
        self._new_chat = dialog
        self._new_chat_el = dialog.dialog.build()
        self.root.container.append(self._new_chat_el)
        await self._render()

    async def open_settings(self) -> None:
        if self._settings_el is not None:
            with contextlib.suppress(ValueError):
                self.root.container.remove(self._settings_el)
        config = self._actions.current_config()
        dialog = SettingsDialog(self._actions, config.login, config.window)
        self._settings_el = dialog.dialog.build()
        self.root.container.append(self._settings_el)
        await self._render()

    async def _select_chat(self, chat: ChatTarget) -> None:
        if self._new_chat is not None:
            self._new_chat.dialog.open = False
        await self._open_and_refresh(chat)

    async def _on_session_selected(self, chat: ChatTarget) -> None:
        await self._open_and_refresh(chat)

    async def _open_and_refresh(self, chat: ChatTarget) -> None:
        await self._actions.open_chat(chat)
        await self._refresh_async()
        await self._actions.scroll_chat_to_bottom()
