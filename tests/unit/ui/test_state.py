"""UI 状态与已读游标测试。"""

import asyncio
from pathlib import Path

from flaza.core.events import MessageReceived
from flaza.core.models import FriendChat, Message, TextElement
from flaza.core.storage import Storage
from flaza.ui.state import UiStateStore


def test_active_chat_marks_incoming_message_read(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        state = UiStateStore(storage)

        chat = FriendChat(uid="u_1", uin=10001)
        state.active_chat.set(chat)
        message = Message(
            chat=chat,
            sender_uin=10001,
            sender_uid="u_1",
            seq=1,
            timestamp=1,
            elements=[TextElement(text="你好")],
        )
        await storage.messages.insert(message)
        await state._on_message_received(MessageReceived(message=message))

        assert await storage.sessions.unread_count(chat) == 0
        await storage.close()

    asyncio.run(scenario())


def test_inactive_chat_keeps_unread_count(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        state = UiStateStore(storage)

        chat = FriendChat(uid="u_1", uin=10001)
        other = FriendChat(uid="u_2", uin=10002)
        state.active_chat.set(other)
        message = Message(
            chat=chat,
            sender_uin=10001,
            sender_uid="u_1",
            seq=1,
            timestamp=1,
            elements=[TextElement(text="你好")],
        )
        await storage.messages.insert(message)
        await state._on_message_received(MessageReceived(message=message))

        assert await storage.sessions.unread_count(chat) == 1
        await storage.close()

    asyncio.run(scenario())
