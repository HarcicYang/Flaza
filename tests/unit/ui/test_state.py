"""UI 状态与已读游标测试。"""

import asyncio
import base64
import json
from pathlib import Path

from flaza.core.events import GroupReactionChanged, MessageMediaCached, MessageRecalled, MessageReceived
from flaza.core.models import FriendChat, GroupChat, ImageElement, Message, StoredMessage, TextElement
from flaza.core.storage import Storage
from flaza.core.storage.codec import encode_message
from flaza.ui.state import CHAT_MESSAGE_PAGE_SIZE, UiStateStore


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


def test_group_reaction_persists_across_message_reload(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        state = UiStateStore(storage)
        chat = GroupChat(group_id=20001)
        message = Message(
            chat=chat,
            sender_uin=10001,
            sender_uid="u_1",
            seq=1,
            timestamp=1,
            elements=[TextElement(text="你好")],
        )
        await storage.messages.insert(message)
        # 模拟启动同步：该群尚未被用户打开，因此没有活跃消息投影。
        state.active_chat.set(FriendChat(uid="u_other", uin=10002))

        await state._on_group_reaction_changed(
            GroupReactionChanged(
                group_id=chat.group_id,
                seq=message.seq,
                emoji_id="😊",
                emoji_type=2,
                count=1,
                is_increase=True,
                operator_uid="u_2",
            )
        )

        reloaded = await storage.messages.list_recent(chat)
        assert reloaded[0].message.reactions[0].emoji_id == "😊"
        assert reloaded[0].message.reactions[0].count == 1
        await state.load_chat(chat)
        assert state.messages()[0].message.reactions[0].emoji_id == "😊"
        await storage.close()

    asyncio.run(scenario())


def test_group_reaction_received_before_message_is_applied_on_insert(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        state = UiStateStore(storage)
        chat = GroupChat(group_id=20001)
        await state._on_group_reaction_changed(
            GroupReactionChanged(
                group_id=chat.group_id,
                seq=2,
                emoji_id="👍",
                emoji_type=2,
                count=3,
                is_increase=True,
                operator_uid="u_2",
            )
        )

        await storage.messages.insert(
            Message(
                chat=chat,
                sender_uin=10001,
                sender_uid="u_1",
                seq=2,
                timestamp=2,
                elements=[TextElement(text="稍后到达")],
            )
        )
        restored = await storage.messages.list_recent(chat)
        assert restored[0].message.reactions[0].emoji_id == "👍"
        assert restored[0].message.reactions[0].count == 3
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


def test_clear_chat_unread_only_updates_local_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        state = UiStateStore(storage)

        target = FriendChat(uid="u_1", uin=10001)
        other = FriendChat(uid="u_2", uin=10002)
        for chat in (target, other):
            await storage.messages.insert(
                Message(
                    chat=chat,
                    sender_uin=chat.uin,
                    sender_uid=chat.uid,
                    seq=1,
                    timestamp=1,
                    elements=[TextElement(text="你好")],
                )
            )
        await state.load_initial_state()

        assert state.clear_chat_unread(target) is True
        sessions = {session.chat.key: session.unread_count for session in state.sessions()}
        assert sessions["friend:u_1"] == 0
        assert sessions["friend:u_2"] == 1
        assert await storage.sessions.unread_count(target) == 1
        await storage.close()

    asyncio.run(scenario())


def test_chat_cache_roundtrip_across_stores(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        state = UiStateStore(storage, chat_cache_path=tmp_path / "chat_cache.json")

        chat = FriendChat(uid="u_1", uin=10001)
        await storage.messages.insert(
            Message(
                chat=chat,
                sender_uin=10001,
                sender_uid="u_1",
                seq=1,
                timestamp=1,
                elements=[TextElement(text="你好")],
            )
        )
        await state.load_chat(chat)
        await state.close_chat_messages_cache()

        restored = UiStateStore(storage, chat_cache_path=tmp_path / "chat_cache.json")
        await restored.load_chat_messages_cache()
        snapshot = restored.peek_chat_messages(chat)
        assert snapshot is not None
        assert [stored.message.text for stored in snapshot.messages] == ["你好"]
        assert snapshot.has_older is False

        await restored.load_chat(chat)
        assert restored.messages()[0].message.text == "你好"
        await restored.close_chat_messages_cache()
        await storage.close()

    asyncio.run(scenario())


def test_chat_cache_roundtrip_preserves_binary_md5(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        state = UiStateStore(storage, chat_cache_path=tmp_path / "chat_cache.json")

        chat = FriendChat(uid="u_1", uin=10001)
        raw_md5 = b"\xb0\xdc\x00\xff"
        await storage.messages.insert(
            Message(
                chat=chat,
                sender_uin=10001,
                sender_uid="u_1",
                seq=1,
                timestamp=1,
                elements=[ImageElement(url="https://example.com/pic.png", md5=raw_md5, size=1)],
            )
        )
        await state.load_chat(chat)
        await state.close_chat_messages_cache()

        restored = UiStateStore(storage, chat_cache_path=tmp_path / "chat_cache.json")
        await restored.load_chat_messages_cache()
        snapshot = restored.peek_chat_messages(chat)
        assert snapshot is not None
        element = snapshot.messages[0].message.elements[0]
        assert isinstance(element, ImageElement)
        assert element.md5 == raw_md5
        await restored.close_chat_messages_cache()
        await storage.close()

    asyncio.run(scenario())


def test_chat_refresh_pages_recent_messages_to_one_screen(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        state = UiStateStore(storage, chat_cache_path=tmp_path / "chat_cache.json")

        chat = FriendChat(uid="u_1", uin=10001)
        total = CHAT_MESSAGE_PAGE_SIZE + 5
        for index in range(1, total + 1):
            await storage.messages.insert(
                Message(
                    chat=chat,
                    sender_uin=10001,
                    sender_uid="u_1",
                    seq=index,
                    timestamp=index,
                    elements=[TextElement(text=str(index))],
                )
            )

        snapshot = await state.refresh_chat_messages(chat)

        assert len(snapshot.messages) == CHAT_MESSAGE_PAGE_SIZE
        assert snapshot.has_older is True
        kept_start = total - CHAT_MESSAGE_PAGE_SIZE + 1
        assert [stored.message.text for stored in snapshot.messages] == [str(i) for i in range(kept_start, total + 1)]
        assert state.peek_chat_messages(chat) == snapshot
        await storage.close()

    asyncio.run(scenario())


def test_chat_cache_load_truncates_oversized_history(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        chat = FriendChat(uid="u_1", uin=10001)
        total = CHAT_MESSAGE_PAGE_SIZE + 5
        messages = [
            StoredMessage(
                id=index,
                message=Message(
                    chat=chat,
                    sender_uin=10001,
                    sender_uid="u_1",
                    seq=index,
                    timestamp=index,
                    elements=[TextElement(text=str(index))],
                ),
            )
            for index in range(1, total + 1)
        ]
        cache_path = tmp_path / "chat_cache.json"
        cache_path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "chats": {
                        chat.key: {
                            "last_message_id": total,
                            "has_older": True,
                            "messages": [
                                {
                                    "id": stored.id,
                                    "message_blob": base64.b64encode(encode_message(stored.message)).decode("ascii"),
                                }
                                for stored in messages
                            ],
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        state = UiStateStore(storage, chat_cache_path=cache_path)
        await state.load_chat_messages_cache()

        snapshot = state.peek_chat_messages(chat)
        assert snapshot is not None
        assert len(snapshot.messages) == CHAT_MESSAGE_PAGE_SIZE
        assert snapshot.has_older is True
        kept_start = total - CHAT_MESSAGE_PAGE_SIZE + 1
        assert [stored.message.text for stored in snapshot.messages] == [str(i) for i in range(kept_start, total + 1)]
        await state.close_chat_messages_cache()
        await storage.close()

    asyncio.run(scenario())


def test_inactive_message_silently_builds_cache_and_prebuild(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        state = UiStateStore(storage, chat_cache_path=tmp_path / "chat_cache.json")
        prebuilt: list[tuple[str, list[int]]] = []
        state.set_chat_prebuilder(
            lambda chat, messages: prebuilt.append((chat.key, [stored.id for stored in messages]))
        )

        active = FriendChat(uid="u_2", uin=10002)
        chat = FriendChat(uid="u_1", uin=10001)
        state.active_chat.set(active)
        await storage.messages.insert(
            Message(
                chat=chat,
                sender_uin=10001,
                sender_uid="u_1",
                seq=1,
                timestamp=1,
                elements=[TextElement(text="新消息")],
            )
        )
        await state._on_message_received(
            MessageReceived(
                message=Message(
                    chat=chat,
                    sender_uin=10001,
                    sender_uid="u_1",
                    seq=1,
                    timestamp=1,
                    elements=[TextElement(text="新消息")],
                )
            )
        )

        assert state.messages() == ()
        await state.close_chat_messages_cache()
        snapshot = state.peek_chat_messages(chat)
        assert snapshot is not None
        assert [stored.message.text for stored in snapshot.messages] == ["新消息"]
        assert prebuilt[-1][0] == chat.key
        await storage.close()

    asyncio.run(scenario())
