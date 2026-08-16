"""消息服务：发送消息与入站消息持久化。"""

from __future__ import annotations

from collections.abc import Sequence

from flaza.core.events import EventBus, MessageReceived, MessageSent
from flaza.core.models import ChatTarget, Message, MessageElement, TextElement
from flaza.core.ports import QQClient
from flaza.core.storage import Storage


class MessageService:
    """消息用例的统一入口。"""

    def __init__(self, qq: QQClient, storage: Storage, bus: EventBus) -> None:
        self._qq = qq
        self._storage = storage
        self._bus = bus

    async def send_message(self, target: ChatTarget, elements: Sequence[MessageElement]) -> Message:
        """通过协议端口发送消息，持久化后发布 MessageSent。"""
        message = await self._qq.send_message(target, elements)
        await self._storage.messages.insert(message)
        self._bus.publish(MessageSent(message=message))
        return message

    async def send_text(self, target: ChatTarget, text: str) -> Message:
        """发送纯文本消息的便利方法。"""
        return await self.send_message(target, [TextElement(text=text)])

    async def on_message_received(self, event: MessageReceived) -> None:
        """入站消息事件处理器：先持久化，再交给后续 UI 订阅者。"""
        await self._storage.messages.insert(event.message)

    async def mark_read(self, chat: ChatTarget, last_read_id: int) -> None:
        """把会话已读游标推进到指定本地消息 id。"""
        await self._storage.messages.mark_read(chat, last_read_id)
