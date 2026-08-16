"""消息服务：发送消息、入站消息持久化与离线补拉。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from flaza.core.events import (
    EventBus,
    MessageMediaCached,
    MessageRecalled,
    MessageReceived,
    MessageSent,
    MessagesSynced,
)
from flaza.core.models import ChatTarget, FriendChat, GroupChat, Message, MessageElement, TextElement
from flaza.core.ports import QQClient
from flaza.core.services.media_cache import MediaCache
from flaza.core.storage import Storage

logger = logging.getLogger(__name__)


class MessageService:
    """消息用例的统一入口。"""

    def __init__(
        self,
        qq: QQClient,
        storage: Storage,
        bus: EventBus,
        media_cache: MediaCache | None = None,
    ) -> None:
        self._qq = qq
        self._storage = storage
        self._bus = bus
        self._media_cache = media_cache
        self._media_tasks: set[asyncio.Task[None]] = set()
        self._scheduled_media: set[tuple[str, int]] = set()

    async def send_message(self, target: ChatTarget, elements: Sequence[MessageElement]) -> Message:
        """通过协议端口发送消息，持久化并标记已读后发布 MessageSent。"""
        message = await self._qq.send_message(target, elements)
        local_id = await self._storage.messages.insert(message)
        await self._storage.messages.mark_read(target, local_id)
        self._bus.publish(MessageSent(message=message))
        return message

    async def send_text(self, target: ChatTarget, text: str) -> Message:
        """发送纯文本消息的便利方法。"""
        return await self.send_message(target, [TextElement(text=text)])

    async def on_message_received(self, event: MessageReceived) -> None:
        """入站消息事件处理器：先持久化，再交给后续 UI 订阅者。"""
        await self._storage.messages.insert(event.message)
        self.schedule_media_cache([event.message])

    async def sync_offline_messages(self, limit_per_chat: int = 500, initial_limit_per_chat: int = 50) -> int:
        """登录后补拉离线消息。

        已有会话从本地最大 seq 之后续拉；尚无会话记录的好友和群也拉取最近
        一段消息，保证离线期间新产生的会话能够出现在会话列表中。
        """
        targets: dict[str, tuple[ChatTarget, int, int]] = {}
        sessions = await self._storage.sessions.list_recent()
        for session in sessions:
            after_seq = await self._storage.messages.latest_seq(session.chat) or 0
            targets[session.chat.key] = (session.chat, after_seq, limit_per_chat)

        for friend in await self._storage.contacts.list_friends():
            chat = FriendChat(uid=friend.uid, uin=friend.uin)
            if chat.key not in targets:
                targets[chat.key] = (chat, 0, initial_limit_per_chat)
        for group in await self._storage.contacts.list_groups():
            chat = GroupChat(group_id=group.group_id)
            if chat.key not in targets:
                targets[chat.key] = (chat, 0, initial_limit_per_chat)

        total = 0
        for chat, after_seq, limit in targets.values():
            try:
                messages = await self._qq.fetch_missing_messages(chat, after_seq, limit)
            except Exception:
                logger.exception("离线消息补拉失败: %s", chat.key)
                continue
            for message in messages:
                await self._storage.messages.insert(message)
            self.schedule_media_cache(messages)
            total += len(messages)

        logger.info("离线消息补拉完成：共 %s 条", total)
        if total:
            self._bus.publish(MessagesSynced(total=total))
        return total

    def schedule_media_cache(self, messages: Sequence[Message]) -> None:
        """为消息中的媒体安排后台缓存任务，不阻塞消息展示。"""
        if self._media_cache is None:
            return
        for message in messages:
            if not self._media_cache.has_cacheable_media(message):
                continue
            key = (message.chat.key, message.seq)
            if key in self._scheduled_media:
                continue
            self._scheduled_media.add(key)
            task = asyncio.create_task(self._cache_message_and_publish(message, key))
            self._media_tasks.add(task)
            task.add_done_callback(self._media_tasks.discard)

    async def cache_message_media(self, message: Message) -> Message | None:
        """下载一条消息的媒体并更新持久化 payload；未变化时返回 None。"""
        if self._media_cache is None:
            return None
        cached = await self._media_cache.cache_message(message)
        if cached == message:
            return None
        updated = await self._storage.messages.update_payload(cached)
        if updated is not None:
            self._bus.publish(MessageMediaCached(message=updated))
            return updated
        return None

    async def stop(self) -> None:
        """取消尚未完成的媒体缓存任务。"""
        tasks = list(self._media_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._media_tasks.clear()
        self._scheduled_media.clear()

    async def _cache_message_and_publish(self, message: Message, key: tuple[str, int]) -> None:
        try:
            await self.cache_message_media(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("消息媒体缓存失败: chat=%s seq=%s", message.chat.key, message.seq, exc_info=True)
        finally:
            self._scheduled_media.discard(key)

    async def mark_read(self, chat: ChatTarget, last_read_id: int) -> None:
        """把会话已读游标推进到指定本地消息 id。"""
        await self._storage.messages.mark_read(chat, last_read_id)

    async def on_message_recalled(self, event: MessageRecalled) -> None:
        """把撤回事件落到对应消息上。"""
        await self._storage.messages.mark_recalled(event.chat, event.seq)
