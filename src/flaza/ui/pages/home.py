"""主窗口页面。"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable

from neony.application.elements import Progress, Text
from neony.dom import Div, DOMElement, Styles

from flaza.config import AppConfig
from flaza.core.events import ContactsUpdated, EventBus, MessageReceived, MessageSent, MessagesSynced, Subscription
from flaza.core.models import ChatTarget
from flaza.ui.actions import UiActions
from flaza.ui.components.composer import Composer
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

        self.session_list = SessionList(state, actions, self._on_session_selected)
        self.message_list = MessageList(state)
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
            container=[sync_root, body],
        )

        self._subscriptions: list[Subscription] = [
            bus.subscribe(MessageReceived, self._on_message),
            bus.subscribe(MessageSent, self._on_message),
            bus.subscribe(MessagesSynced, self._on_messages_synced),
            bus.subscribe(ContactsUpdated, self._on_contacts_updated),
        ]
        self._refresh()

    # ---- 数据刷新 ----

    def _refresh(self) -> None:
        sessions = list(self._state.sessions())
        self.session_list.set_sessions(sessions)
        active = self._state.active_chat()
        self.message_list.set_messages(active, self._state.messages())

    async def _refresh_async(self) -> None:
        self._refresh()
        await self._render()

    async def _on_message(self, _event: MessageReceived | MessageSent) -> None:
        await self._refresh_async()
        await self._actions.scroll_chat_to_bottom()

    async def _on_contacts_updated(self, _event: ContactsUpdated) -> None:
        await self._refresh_async()

    async def _on_messages_synced(self, _event: MessagesSynced) -> None:
        await self._refresh_async()

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
        dialog = SettingsDialog(self._actions, self._config.login)
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
