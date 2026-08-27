"""UI 状态：领域事件到 Neony Signal 的投影。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    GroupReactionChanged,
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
    GroupChat,
    GroupMemberRole,
    LoginPhase,
    Message,
    MessageElement,
    SelfInfo,
    Session,
    StoredMessage,
)
from flaza.core.storage import Storage
from flaza.core.storage.codec import decode_message, encode_message

logger = logging.getLogger(__name__)

RenderCallback = Callable[[], Awaitable[None]]

_STARTUP_WARM_CHATS = 6
CHAT_MESSAGE_PAGE_SIZE = 20


@dataclass(frozen=True)
class ChatMessagesSnapshot:
    """一个会话最近消息的内存/磁盘投影，供切换会话时快速恢复。"""

    messages: tuple[StoredMessage, ...]
    has_older: bool
    last_message_id: int = 0


def _stored_message_from_cache_entry(entry: dict[str, Any]) -> StoredMessage:
    """恢复缓存消息；版本 1 使用完整模型 JSON，版本 2 使用消息编码 blob。"""
    message_blob = entry.get("message_blob")
    if message_blob is None:
        return StoredMessage.model_validate(entry)
    return StoredMessage(
        id=int(entry["id"]),
        message=decode_message(base64.b64decode(message_blob)),
    )


class ChatNotice:
    """聊天流中的派生灰条。"""

    def __init__(self, chat_key: str, text: str, timestamp: int, key: str) -> None:
        self.chat_key = chat_key
        self.text = text
        self.timestamp = timestamp
        self.key = key


class UiStateStore:
    """持有可绑定到 Neony 组件的响应式状态。"""

    def __init__(
        self,
        storage: Storage,
        render: RenderCallback | None = None,
        *,
        chat_cache_path: str | Path | None = None,
    ) -> None:
        self._storage = storage
        self._render = render
        self._chat_cache_path = Path(chat_cache_path) if chat_cache_path else None

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
        self.pending_messages = Signal[tuple[StoredMessage, ...]](())
        self.notices = Signal[tuple[ChatNotice, ...]](())
        self.group_roles = Signal[dict[str, GroupMemberRole]]({})
        self.has_older_messages = Signal(False)
        self.reply_to = Signal[StoredMessage | None](None)
        self._state_refresh_suppressed = 0
        self._chat_messages_cache: dict[str, ChatMessagesSnapshot] = {}
        self._chat_cache_dirty = False
        self._chat_cache_closed = False
        self._chat_cache_save_task: asyncio.Task[None] | None = None
        self._chat_cache_refresh_tasks: dict[str, asyncio.Task[ChatMessagesSnapshot]] = {}
        self._chat_cache_refresh_dirty: dict[str, bool] = {}
        self._chat_prebuilder: Callable[[ChatTarget, tuple[StoredMessage, ...]], None] | None = None
        self._warm_sessions_task: asyncio.Task[None] | None = None
        self._next_pending_id = -1

    def set_render(self, render: RenderCallback | None) -> None:
        """注入 Neony 渲染回调，由应用组装根调用。"""
        self._render = render

    @contextmanager
    def suppress_state_refresh(self):
        """临时禁止 HomePage 的 Signal effect 触发独立刷新。"""
        self._state_refresh_suppressed += 1
        try:
            yield
        finally:
            self._state_refresh_suppressed -= 1

    @property
    def state_refresh_suppressed(self) -> bool:
        return self._state_refresh_suppressed > 0

    def set_chat_prebuilder(
        self,
        prebuilder: Callable[[ChatTarget, tuple[StoredMessage, ...]], None],
    ) -> None:
        """注册会话消息的 DOM 静默预建回调。"""
        self._chat_prebuilder = prebuilder

    def peek_chat_messages(self, chat: ChatTarget) -> ChatMessagesSnapshot | None:
        """返回最近消息缓存；未缓存时返回 None。"""
        return self._chat_messages_cache.get(chat.key)

    def remember_chat_messages(
        self,
        chat: ChatTarget,
        messages: list[StoredMessage] | tuple[StoredMessage, ...],
        has_older: bool,
    ) -> None:
        """把最近消息投影写入会话快照缓存。"""
        stored = tuple(messages)
        self._chat_messages_cache[chat.key] = ChatMessagesSnapshot(
            messages=stored,
            has_older=has_older,
            last_message_id=stored[-1].id if stored else 0,
        )
        self._chat_cache_dirty = True
        self._schedule_chat_cache_save()

    async def persist_chat_messages_cache(self) -> None:
        """把会话快照缓存落盘；未配置缓存路径时直接跳过。"""
        if self._chat_cache_path is None:
            self._chat_cache_dirty = False
            return
        payload = {
            "version": 2,
            "chats": {
                key: {
                    "last_message_id": snapshot.last_message_id,
                    "has_older": snapshot.has_older,
                    "messages": [
                        {
                            "id": stored.id,
                            "message_blob": base64.b64encode(encode_message(stored.message)).decode("ascii"),
                        }
                        for stored in snapshot.messages
                    ],
                }
                for key, snapshot in self._chat_messages_cache.items()
            },
        }
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        cache_path = self._chat_cache_path

        def write_cache() -> None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = cache_path.with_name(f"{cache_path.name}.tmp")
            tmp_path.write_text(data, encoding="utf-8")
            tmp_path.replace(cache_path)

        await asyncio.to_thread(write_cache)
        self._chat_cache_dirty = False

    async def load_chat_messages_cache(self) -> None:
        """启动时恢复上次退出前的会话快照缓存。"""
        if self._chat_cache_path is None:
            return
        if not self._chat_cache_path.exists():
            return
        try:
            data = await asyncio.to_thread(self._chat_cache_path.read_text, encoding="utf-8")
            payload = json.loads(data)
            if payload.get("version") not in (1, 2):
                return
            for key, entry in payload.get("chats", {}).items():
                raw_messages = entry.get("messages") or []
                messages = tuple(_stored_message_from_cache_entry(item) for item in raw_messages)
                has_older = bool(entry.get("has_older", False)) or len(raw_messages) > CHAT_MESSAGE_PAGE_SIZE
                messages = messages[-CHAT_MESSAGE_PAGE_SIZE:]
                self._chat_messages_cache[key] = ChatMessagesSnapshot(
                    messages=messages,
                    has_older=has_older,
                    last_message_id=int(entry.get("last_message_id") or (messages[-1].id if messages else 0)),
                )
        except Exception:
            logger.exception("加载会话快照缓存失败: %s", self._chat_cache_path)

    def schedule_chat_messages_refresh(self, chat: ChatTarget) -> None:
        """后台静默刷新会话最近消息缓存，不阻塞当前 UI。"""
        key = chat.key
        task = self._chat_cache_refresh_tasks.get(key)
        if task is not None and not task.done():
            self._chat_cache_refresh_dirty[key] = True
            return
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._chat_messages_refresh_runner(chat, key), name=f"flaza-chat-cache:{key}")
        self._chat_cache_refresh_tasks[key] = task
        task.add_done_callback(self._chat_cache_refresh_done)

    async def refresh_chat_messages(self, chat: ChatTarget) -> ChatMessagesSnapshot:
        """读取会话最近消息并写入缓存；相同会话的并发刷新会合并。"""
        key = chat.key
        task = self._chat_cache_refresh_tasks.get(key)
        if task is not None and not task.done():
            return await task
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._chat_messages_refresh_runner(chat, key), name=f"flaza-chat-cache:{key}")
        self._chat_cache_refresh_tasks[key] = task
        task.add_done_callback(self._chat_cache_refresh_done)
        return await task

    async def _chat_messages_refresh_runner(
        self,
        chat: ChatTarget,
        key: str,
    ) -> ChatMessagesSnapshot:
        try:
            while True:
                snapshot = await self._load_chat_messages_snapshot(chat)
                self.remember_chat_messages(chat, snapshot.messages, snapshot.has_older)
                if self._chat_prebuilder is not None:
                    try:
                        self._chat_prebuilder(chat, snapshot.messages)
                    except Exception:
                        logger.exception("预建会话消息失败: chat=%s", chat.key)
                if not self._chat_cache_refresh_dirty.pop(key, False):
                    return snapshot
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("刷新会话消息缓存失败: chat=%s", chat.key)
            raise
        finally:
            self._chat_cache_refresh_tasks.pop(key, None)

    def begin_outgoing_message(self, chat: ChatTarget, elements: Sequence[MessageElement]) -> StoredMessage:
        """把尚未确认的消息加入聊天流的乐观投影。

        负数本地 ID 只存在于 UI 状态中；真实消息入库后使用正数 ID，
        因此不会与会话缓存或存储层冲突。
        """
        info = self.self_info()
        message = Message(
            chat=chat,
            sender_uin=info.uin if info else 0,
            sender_uid=info.uid if info else "",
            sender_name=info.nickname if info else "我",
            seq=0,
            timestamp=int(time.time()),
            elements=list(elements),
            from_self=True,
        )
        stored = StoredMessage(id=self._next_pending_id, message=message)
        self._next_pending_id -= 1
        self.pending_messages.set((*self.pending_messages(), stored))
        return stored

    def remove_pending_message(self, stored: StoredMessage) -> None:
        """按乐观 ID 移除待确认消息；重复移除是安全的。"""
        pending = tuple(item for item in self.pending_messages() if item.id != stored.id)
        if pending != self.pending_messages():
            self.pending_messages.set(pending)

    async def _load_chat_messages_snapshot(self, chat: ChatTarget) -> ChatMessagesSnapshot:
        messages, has_older = await self._storage.messages.list_recent_with_has_before(
            chat,
            limit=CHAT_MESSAGE_PAGE_SIZE,
        )
        return ChatMessagesSnapshot(
            messages=tuple(messages),
            has_older=has_older,
            last_message_id=messages[-1].id if messages else 0,
        )

    def _chat_cache_refresh_done(self, task: asyncio.Task[ChatMessagesSnapshot]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("后台会话刷新任务失败", exc_info=error)

    async def close_chat_messages_cache(self) -> None:
        """等待后台刷新队列并把最终缓存落盘；应用退出前调用。"""
        if self._chat_cache_closed:
            return
        self._chat_cache_closed = True
        pending = list(self._chat_cache_refresh_tasks.values())
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        save_task = self._chat_cache_save_task
        self._chat_cache_save_task = None
        if save_task is not None:
            save_task.cancel()
            await asyncio.gather(save_task, return_exceptions=True)
        self._chat_cache_dirty = True
        await self.persist_chat_messages_cache()

    def _schedule_chat_cache_save(self) -> None:
        if self._chat_cache_closed or self._chat_cache_path is None or self._chat_cache_save_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._save_chat_cache_soon())
        self._chat_cache_save_task = task
        task.add_done_callback(self._chat_cache_save_done)

    def _chat_cache_save_done(self, task: asyncio.Task[None]) -> None:
        self._chat_cache_save_task = None
        if self._chat_cache_dirty and not task.cancelled() and not self._chat_cache_closed:
            self._schedule_chat_cache_save()

    async def _save_chat_cache_soon(self) -> None:
        try:
            await asyncio.sleep(2)
            await self.persist_chat_messages_cache()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("写入会话快照缓存失败")

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
        bus.subscribe(GroupReactionChanged, self._on_group_reaction_changed)

    async def load_initial_state(self) -> None:
        """启动时从存储恢复联系人与会话摘要。"""
        await self.load_chat_messages_cache()
        self.friends.set(tuple(await self._storage.contacts.list_friends()))
        self.groups.set(tuple(await self._storage.contacts.list_groups()))
        await self.refresh_sessions()
        self._schedule_startup_chat_refresh()

    async def load_chat(self, chat: ChatTarget) -> None:
        """切换当前会话并加载最近消息。"""
        self.active_chat.set(chat)
        snapshot = self.peek_chat_messages(chat)
        if snapshot is None:
            snapshot = await self.refresh_chat_messages(chat)
        assert snapshot is not None
        self.messages.set(snapshot.messages)
        self.has_older_messages.set(snapshot.has_older)
        await self._request_render()

    def _schedule_startup_chat_refresh(self) -> None:
        """后台预取最近会话；已在运行的预热任务会复用。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._warm_sessions_task is not None and not self._warm_sessions_task.done():
            return
        task = loop.create_task(self._warm_startup_chats())
        self._warm_sessions_task = task
        task.add_done_callback(self._warm_sessions_done)

    def _warm_sessions_done(self, task: asyncio.Task[None]) -> None:
        self._warm_sessions_task = None
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("后台预取会话失败", exc_info=error)

    async def _warm_startup_chats(self) -> None:
        sessions = self.sessions()[:_STARTUP_WARM_CHATS]
        for session in sessions:
            try:
                chat = session.chat
                latest_id = await self._storage.messages.latest_id(chat)
                snapshot = self.peek_chat_messages(chat)
                if snapshot is not None and (latest_id or 0) == snapshot.last_message_id:
                    if self._chat_prebuilder is not None:
                        try:
                            self._chat_prebuilder(chat, snapshot.messages)
                        except Exception:
                            logger.exception("预建会话消息失败: chat=%s", chat.key)
                    continue
                await self.refresh_chat_messages(chat)
            except Exception:
                logger.exception("后台预热会话失败: chat=%s", session.chat.key)

    async def refresh_sessions(self) -> None:
        """从存储重新加载会话摘要。"""
        sessions = await self._storage.sessions.list_recent()
        self.sessions.set(tuple(sessions))

    def clear_chat_unread(self, chat: ChatTarget) -> bool:
        """本地把指定会话的未读数清零，返回该会话是否已出现在列表中。"""
        sessions = self.sessions()
        found = any(session.chat.key == chat.key for session in sessions)
        updated = tuple(
            session.model_copy(update={"unread_count": 0})
            if session.chat.key == chat.key and session.unread_count
            else session
            for session in sessions
        )
        if updated != sessions:
            self.sessions.set(updated)
        return found

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
            snapshot = await self.refresh_chat_messages(active_chat)
            self.messages.set(snapshot.messages)
            self.has_older_messages.set(snapshot.has_older)
        else:
            self.schedule_chat_messages_refresh(event.message.chat)

    async def _on_messages_synced(self, _event: MessagesSynced) -> None:
        active_chat = self.active_chat()
        if active_chat is not None:
            await self._mark_active_chat_read(active_chat)
            snapshot = await self.refresh_chat_messages(active_chat)
            self.messages.set(snapshot.messages)
            self.has_older_messages.set(snapshot.has_older)
        await self.refresh_sessions()
        self._schedule_startup_chat_refresh()

    async def _refresh_for_message(self, message: Message) -> None:
        active_chat = self.active_chat()
        if active_chat is not None and active_chat.key == message.chat.key:
            await self._mark_active_chat_read(active_chat)
            snapshot = await self.refresh_chat_messages(active_chat)
            self.messages.set(snapshot.messages)
            self.has_older_messages.set(snapshot.has_older)
            logger.info("消息状态已刷新: chat=%s count=%s", active_chat.key, len(snapshot.messages))
        else:
            self.schedule_chat_messages_refresh(message.chat)
            logger.info(
                "消息不属于当前会话: active=%s message=%s", active_chat.key if active_chat else None, message.chat.key
            )
        await self.refresh_sessions()

    async def _mark_active_chat_read(self, chat: ChatTarget) -> None:
        await self._storage.messages.mark_all_read(chat)

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
        self.schedule_chat_messages_refresh(event.chat)
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

    async def _on_group_reaction_changed(self, event: GroupReactionChanged) -> None:
        await self.update_group_reaction(event)

    async def update_group_reaction(self, event: GroupReactionChanged) -> None:
        """持久化群表情事件，并在当前会话可见时更新投影。"""
        chat = GroupChat(group_id=event.group_id)
        persisted = await self._storage.messages.apply_group_reaction(
            chat,
            event.seq,
            event.emoji_id,
            event.emoji_type,
            event.count,
            is_increase=event.is_increase,
            operator_uid=event.operator_uid,
        )
        if persisted is None:
            return

        self.schedule_chat_messages_refresh(chat)
        active_chat = self.active_chat()
        if active_chat is None or active_chat.key != chat.key:
            return

        messages = list(self.messages())
        for index, stored in enumerate(messages):
            if stored.id == persisted.id:
                messages[index] = persisted
                self.messages.set(tuple(messages))
                return

    def _append_notice(self, chat_key: str, text: str, timestamp: int, key: str) -> None:
        notices = list(self.notices())
        if any(notice.key == key for notice in notices):
            return
        notices.append(ChatNotice(chat_key=chat_key, text=text, timestamp=timestamp, key=key))
        self.notices.set(tuple(notices))

    async def _request_render(self) -> None:
        if self._render is not None:
            await self._render()
