"""UI 状态与已读游标测试。"""

import asyncio
from pathlib import Path

from flaza.core.events import MessageMediaCached, MessageRecalled, MessageReceived
from flaza.core.models import FriendChat, ImageElement, Message, TextElement
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


def test_media_cached_event_refreshes_active_chat(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        state = UiStateStore(storage)

        chat = FriendChat(uid="u_1", uin=10001)
        original = Message(
            chat=chat,
            sender_uin=10001,
            sender_uid="u_1",
            seq=1,
            timestamp=1,
            elements=[ImageElement(url="https://example.com/pic.png", md5=b"m", size=1)],
        )
        await storage.messages.insert(original)
        state.active_chat.set(chat)
        state.messages.set(tuple(await storage.messages.list_recent(chat)))

        cached = original.model_copy(
            update={"elements": [original.elements[0].model_copy(update={"cached_path": "/tmp/pic.png"})]}
        )
        await storage.messages.update_payload(cached)
        await state._on_message_media_cached(MessageMediaCached(message=cached))

        stored = state.messages()
        element = stored[0].message.elements[0]
        assert isinstance(element, ImageElement)
        assert element.cached_path == "/tmp/pic.png"
        await storage.close()

    asyncio.run(scenario())


def test_recalled_event_updates_message_without_duplicate_notice(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        state = UiStateStore(storage)

        chat = FriendChat(uid="u_1", uin=10001)
        message = Message(
            chat=chat,
            sender_uin=10001,
            sender_uid="u_1",
            seq=1,
            timestamp=1,
            elements=[TextElement(text="你好")],
        )
        local_id = await storage.messages.insert(message)
        state.active_chat.set(chat)
        state.messages.set(tuple(await storage.messages.list_recent(chat)))

        await state._on_message_recalled(MessageRecalled(chat=chat, seq=1, timestamp=2))

        stored = state.messages()
        assert stored[0].id == local_id
        assert stored[0].message.recalled is True
        assert state.notices() == ()
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
