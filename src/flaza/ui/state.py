"""UI 状态：领域事件到 Neony Signal 的投影。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from neony.dom import Signal

from flaza.core.events import (
    ConnectionStateChanged,
    ContactsUpdated,
    EventBus,
    GroupAdminChanged,
    GroupMemberJoined,
    GroupMemberMuted,
    GroupMemberQuit,
    GroupMembersUpdated,
    GroupNameChanged,
    LoginPhaseChanged,
    MessageMediaCached,
    MessageRecalled,
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
    GroupMemberRole,
    LoginPhase,
    Message,
    SelfInfo,
    Session,
    StoredMessage,
)
from flaza.core.storage import Storage

logger = logging.getLogger(__name__)

RenderCallback = Callable[[], Awaitable[None]]


class ChatNotice:
    """聊天流中的派生灰条。"""

    def __init__(self, chat_key: str, text: str, timestamp: int, key: str) -> None:
        self.chat_key = chat_key
        self.text = text
        self.timestamp = timestamp
        self.key = key


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
        self.notices = Signal[tuple[ChatNotice, ...]](())
        self.group_roles = Signal[dict[str, GroupMemberRole]]({})
        self.has_older_messages = Signal(False)

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
        bus.subscribe(MessageMediaCached, self._on_message_media_cached)
        bus.subscribe(MessagesSynced, self._on_messages_synced)
        bus.subscribe(MessageRecalled, self._on_message_recalled)
        bus.subscribe(GroupNameChanged, self._on_group_name_changed)
        bus.subscribe(GroupMemberJoined, self._on_group_member_joined)
        bus.subscribe(GroupMemberQuit, self._on_group_member_quit)
        bus.subscribe(GroupAdminChanged, self._on_group_admin_changed)
        bus.subscribe(GroupMemberMuted, self._on_group_member_muted)
        bus.subscribe(GroupMembersUpdated, self._on_group_members_updated)

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
        self.has_older_messages.set(bool(messages) and await self._storage.messages.has_before(chat, messages[0].id))
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

    async def _on_message_received(self, event: MessageReceived) -> None:
        await self._refresh_for_message(event.message)

    async def _on_message_sent(self, event: MessageSent) -> None:
        await self._refresh_for_message(event.message)

    async def _on_message_media_cached(self, event: MessageMediaCached) -> None:
        """媒体缓存完成后刷新当前会话，让气泡切换到本地文件。"""
        active_chat = self.active_chat()
        if active_chat is not None and active_chat.key == event.message.chat.key:
            messages = await self._storage.messages.list_recent(active_chat)
            self.messages.set(tuple(messages))

    async def _on_messages_synced(self, _event: MessagesSynced) -> None:
        active_chat = self.active_chat()
        if active_chat is not None:
            await self._mark_active_chat_read(active_chat)
            messages = await self._storage.messages.list_recent(active_chat)
            self.messages.set(tuple(messages))
        await self.refresh_sessions()

    async def _refresh_for_message(self, message: Message) -> None:
        active_chat = self.active_chat()
        if active_chat is not None and active_chat.key == message.chat.key:
            await self._mark_active_chat_read(active_chat)
            messages = await self._storage.messages.list_recent(active_chat)
            self.messages.set(tuple(messages))
            logger.info("消息状态已刷新: chat=%s count=%s", active_chat.key, len(messages))
        else:
            logger.info(
                "消息不属于当前会话: active=%s message=%s", active_chat.key if active_chat else None, message.chat.key
            )
        await self.refresh_sessions()

    async def _mark_active_chat_read(self, chat: ChatTarget) -> None:
        latest_id = await self._storage.messages.latest_id(chat)
        if latest_id is not None:
            await self._storage.messages.mark_read(chat, latest_id)

    async def _on_message_recalled(self, event: MessageRecalled) -> None:
        messages = []
        for stored in self.messages():
            if stored.message.chat.key == event.chat.key and stored.message.seq == event.seq:
                stored = StoredMessage(
                    id=stored.id,
                    message=stored.message.model_copy(update={"recalled": True}),
                )
            messages.append(stored)
        self.messages.set(tuple(messages))
        # 撤回灰条由 recalled 消息在原位渲染，不再额外追加 notice，避免同一条撤回显示两次。
        await self.refresh_sessions()

    async def _on_group_name_changed(self, event: GroupNameChanged) -> None:
        groups = tuple(
            group.model_copy(update={"name": event.name_new}) if group.group_id == event.group_id else group
            for group in self.groups()
        )
        self.groups.set(groups)
        self._append_notice(
            f"group:{event.group_id}",
            f"群名已修改为“{event.name_new}”",
            event.timestamp,
            f"name:{event.group_id}:{event.timestamp}",
        )
        await self.refresh_sessions()

    async def _on_group_member_joined(self, event: GroupMemberJoined) -> None:
        self._append_notice(
            f"group:{event.group_id}",
            "有成员加入群聊",
            event.timestamp,
            f"join:{event.group_id}:{event.uid}:{event.timestamp}",
        )

    async def _on_group_member_quit(self, event: GroupMemberQuit) -> None:
        text = "有成员退出群聊"
        if event.is_kicked:
            text = "有成员被移出群聊"
        roles = dict(self.group_roles())
        roles.pop(f"{event.group_id}:{event.uid}", None)
        self.group_roles.set(roles)
        self._append_notice(
            f"group:{event.group_id}", text, event.timestamp, f"quit:{event.group_id}:{event.uid}:{event.timestamp}"
        )

    async def _on_group_admin_changed(self, event: GroupAdminChanged) -> None:
        key = f"{event.group_id}:{event.uid}"
        roles = dict(self.group_roles())
        roles[key] = GroupMemberRole.ADMIN if event.is_set else GroupMemberRole.MEMBER
        self.group_roles.set(roles)
        text = "设置了新的管理员" if event.is_set else "取消了管理员"
        self._append_notice(f"group:{event.group_id}", text, event.timestamp, f"admin:{key}:{event.timestamp}")

    async def _on_group_member_muted(self, event: GroupMemberMuted) -> None:
        text = "开启了全员禁言" if not event.target_uid else f"有成员被禁言 {event.duration} 秒"
        self._append_notice(
            f"group:{event.group_id}",
            text,
            event.timestamp,
            f"mute:{event.group_id}:{event.target_uid}:{event.timestamp}",
        )

    async def _on_group_members_updated(self, event: GroupMembersUpdated) -> None:
        roles = dict(self.group_roles())
        for member in event.members:
            roles[f"{member.group_id}:{member.uid}"] = member.role
        self.group_roles.set(roles)

    def _append_notice(self, chat_key: str, text: str, timestamp: int, key: str) -> None:
        notices = list(self.notices())
        if any(notice.key == key for notice in notices):
            return
        notices.append(ChatNotice(chat_key=chat_key, text=text, timestamp=timestamp, key=key))
        self.notices.set(tuple(notices))

    async def _request_render(self) -> None:
        if self._render is not None:
            await self._render()
