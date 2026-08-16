"""UI 状态：领域事件到 Neony Signal 的投影。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from neony.dom import Signal

from flaza.core.events import (
    ConnectionStateChanged,
    ContactsUpdated,
    EventBus,
    LoginPhaseChanged,
    MessageReceived,
    MessageSent,
    MessagesSynced,
    QrCodeReady,
    SelfInfoChanged,
)
from flaza.core.models import (
    ChatTarget,
    ConnectionState,
    Friend,
    Group,
    LoginPhase,
    Message,
    SelfInfo,
    Session,
    StoredMessage,
)
from flaza.core.storage import Storage

logger = logging.getLogger(__name__)

RenderCallback = Callable[[], Awaitable[None]]


class UiStateStore:
    """持有可绑定到 Neony 组件的响应式状态。"""

    def __init__(self, storage: Storage, render: RenderCallback | None = None) -> None:
        self._storage = storage
        self._render = render

        self.login_phase = Signal(LoginPhase.IDLE)
        self.login_detail = Signal("")
        self.sync_in_progress = Signal(False)
        self.connection_state = Signal(ConnectionState.CONNECTING)
        self.qr_image = Signal[bytes | None](None)
        self.self_info = Signal[SelfInfo | None](None)
        self.friends = Signal[tuple[Friend, ...]](())
        self.groups = Signal[tuple[Group, ...]](())
        self.sessions = Signal[tuple[Session, ...]](())
        self.active_chat = Signal[ChatTarget | None](None)
        self.active_chat_title = Signal("")
        self.messages = Signal[tuple[StoredMessage, ...]](())

    def set_render(self, render: RenderCallback | None) -> None:
        """注入 Neony 渲染回调，由应用组装根调用。"""
        self._render = render

    def wire(self, bus: EventBus) -> None:
        """订阅领域事件并更新响应式状态。"""
        bus.subscribe(LoginPhaseChanged, self._on_login_phase_changed)
        bus.subscribe(QrCodeReady, self._on_qrcode_ready)
        bus.subscribe(ConnectionStateChanged, self._on_connection_state_changed)
        bus.subscribe(SelfInfoChanged, self._on_self_info_changed)
        bus.subscribe(ContactsUpdated, self._on_contacts_updated)
        bus.subscribe(MessageReceived, self._on_message_received)
        bus.subscribe(MessageSent, self._on_message_sent)
        bus.subscribe(MessagesSynced, self._on_messages_synced)

    async def load_initial_state(self) -> None:
        """启动时从存储恢复联系人与会话摘要。"""
        self.friends.set(tuple(await self._storage.contacts.list_friends()))
        self.groups.set(tuple(await self._storage.contacts.list_groups()))
        await self.refresh_sessions()

    async def load_chat(self, chat: ChatTarget) -> None:
        """切换当前会话并加载最近消息。"""
        self.active_chat.set(chat)
        messages = await self._storage.messages.list_recent(chat)
        self.messages.set(tuple(messages))
        await self._request_render()

    async def refresh_sessions(self) -> None:
        """从存储重新加载会话摘要。"""
        sessions = await self._storage.sessions.list_recent()
        self.sessions.set(tuple(sessions))

    # ---- 事件处理器 ----

    async def _on_login_phase_changed(self, event: LoginPhaseChanged) -> None:
        self.login_phase.set(event.phase)
        self.login_detail.set(event.detail)
        await self._request_render()

    async def _on_qrcode_ready(self, event: QrCodeReady) -> None:
        self.qr_image.set(event.qr.image)
        await self._request_render()

    async def _on_connection_state_changed(self, event: ConnectionStateChanged) -> None:
        self.connection_state.set(event.state)
        await self._request_render()

    async def _on_self_info_changed(self, event: SelfInfoChanged) -> None:
        self.self_info.set(event.info)
        await self._request_render()

    async def _on_contacts_updated(self, event: ContactsUpdated) -> None:
        self.friends.set(tuple(event.friends))
        self.groups.set(tuple(event.groups))
        await self._request_render()

    async def _on_message_received(self, event: MessageReceived) -> None:
        await self._refresh_for_message(event.message)

    async def _on_message_sent(self, event: MessageSent) -> None:
        await self._refresh_for_message(event.message)

    async def _on_messages_synced(self, _event: MessagesSynced) -> None:
        await self.refresh_sessions()
        active_chat = self.active_chat()
        if active_chat is not None:
            messages = await self._storage.messages.list_recent(active_chat)
            self.messages.set(tuple(messages))
        await self._request_render()

    async def _refresh_for_message(self, message: Message) -> None:
        await self.refresh_sessions()
        active_chat = self.active_chat()
        if active_chat is not None and active_chat.key == message.chat.key:
            messages = await self._storage.messages.list_recent(active_chat)
            self.messages.set(tuple(messages))
        await self._request_render()

    async def _request_render(self) -> None:
        if self._render is not None:
            await self._render()
