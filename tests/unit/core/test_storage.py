"""异步 SQLite 存储集成测试。"""

import asyncio
import sqlite3
from pathlib import Path

import aiosqlite
import msgpack

from flaza.core.models import (
    Friend,
    FriendChat,
    Group,
    GroupChat,
    GroupMember,
    GroupMemberRole,
    ImageElement,
    Message,
    PokeElement,
    TextElement,
)
from flaza.core.storage import Storage
from flaza.core.storage.codec import decode_message, encode_message
from flaza.ui.state import UiStateStore


def test_storage_migrates_existing_database(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "old.db"
        db = await aiosqlite.connect(path)
        db.row_factory = sqlite3.Row
        await db.execute(
            "CREATE TABLE groups (group_id INTEGER PRIMARY KEY, name TEXT, member_count INTEGER, updated_at INTEGER)"
        )
        await db.execute(
            "CREATE TABLE messages ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_kind TEXT, chat_id TEXT, sender_uin INTEGER, "
            "seq INTEGER, client_seq INTEGER, rand INTEGER, timestamp INTEGER, from_self INTEGER, "
            "text TEXT, payload BLOB, UNIQUE(chat_kind, chat_id, seq))"
        )
        await db.commit()
        await db.close()

        storage = Storage()
        await storage.init(path)
        cursor = await storage.require_db().execute("PRAGMA table_info(messages)")
        columns = {row["name"] for row in await cursor.fetchall()}
        assert "recalled" in columns
        cursor = await storage.require_db().execute("PRAGMA table_info(groups)")
        columns = {row["name"] for row in await cursor.fetchall()}
        assert "owner_uid" in columns
        await storage.close()

    asyncio.run(scenario())


def test_codec_decodes_legacy_text_only_payload() -> None:
    """旧版本只存 TextElement 的 payload 仍可由扩展后的联合模型解析。"""
    chat = FriendChat(uid="u_1", uin=10001)
    legacy_message = Message(
        chat=chat,
        sender_uin=10001,
        sender_uid="u_1",
        seq=1,
        timestamp=100,
        elements=[TextElement(text="旧消息")],
    )
    blob = msgpack.packb({"version": 1, "message": legacy_message.model_dump(mode="python")}, use_bin_type=True)
    if blob is None:
        raise AssertionError("msgpack 编码失败")

    decoded = decode_message(blob)
    assert decoded == legacy_message
    assert isinstance(decoded.elements[0], TextElement)
    assert decoded.text == "旧消息"


def test_codec_roundtrips_non_text_elements() -> None:
    message = Message(
        chat=FriendChat(uid="u_1", uin=10001),
        sender_uin=10001,
        sender_uid="u_1",
        seq=1,
        timestamp=100,
        elements=[
            TextElement(text="看图："),
            ImageElement(url="https://example.com/pic.png", width=640, height=480),
            PokeElement(id=1),
        ],
    )

    decoded = decode_message(encode_message(message))
    assert decoded == message
    assert decoded.text == "看图：[图片][戳一戳]"


def test_storage_persists_non_text_elements(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")

        chat = FriendChat(uid="u_1", uin=10001)
        message = Message(
            chat=chat,
            sender_uin=10001,
            sender_uid="u_1",
            seq=10,
            timestamp=100,
            elements=[
                TextElement(text="看图："),
                ImageElement(url="https://example.com/pic.png", width=640, height=480),
                PokeElement(id=1),
            ],
        )
        await storage.messages.insert(message)

        stored = await storage.messages.list_recent(chat)
        assert len(stored) == 1
        assert [type(element) for element in stored[0].message.elements] == [TextElement, ImageElement, PokeElement]
        assert stored[0].message.text == "看图：[图片][戳一戳]"

        sessions = await storage.sessions.list_recent()
        assert sessions[0].last_text == "看图：[图片][戳一戳]"
        await storage.close()

    asyncio.run(scenario())


def test_update_payload_preserves_recalled_state(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")

        chat = FriendChat(uid="u_1", uin=10001)
        original = Message(
            chat=chat,
            sender_uin=10001,
            sender_uid="u_1",
            seq=10,
            timestamp=100,
            elements=[ImageElement(url="https://example.com/pic.png", md5=b"m", size=1)],
        )
        await storage.messages.insert(original)
        assert await storage.messages.mark_recalled(chat, 10) is True

        cached = original.model_copy(
            update={"elements": [original.elements[0].model_copy(update={"cached_path": "/tmp/pic.png"})]}
        )
        persisted = await storage.messages.update_payload(cached)
        assert persisted is not None
        assert persisted.recalled is True
        element = persisted.elements[0]
        assert isinstance(element, ImageElement)
        assert element.cached_path == "/tmp/pic.png"

        stored = await storage.messages.list_recent(chat)
        assert stored[0].message.recalled is True
        await storage.close()

    asyncio.run(scenario())


def test_storage_mark_recalled_and_member_roles(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")

        chat = GroupChat(group_id=20002)
        await storage.messages.insert(
            Message(
                chat=chat, sender_uin=1, sender_uid="u_1", seq=10, timestamp=100, elements=[TextElement(text="机密")]
            )
        )
        assert await storage.messages.mark_recalled(chat, 10) is True
        recalled = await storage.messages.list_recent(chat)
        assert recalled[0].message.recalled is True

        member = GroupMember(group_id=20002, uid="u_1", uin=1, nickname="小明", role=GroupMemberRole.ADMIN)
        await storage.members.upsert(member)
        cached = await storage.members.get(20002, "u_1")
        assert cached is not None and cached.role is GroupMemberRole.ADMIN
        await storage.members.set_role(20002, "u_1", GroupMemberRole.OWNER)
        cached = await storage.members.get(20002, "u_1")
        assert cached is not None and cached.role is GroupMemberRole.OWNER
        await storage.members.remove(20002, "u_1")
        assert await storage.members.get(20002, "u_1") is None

        sessions = await storage.sessions.list_recent()
        assert sessions[0].last_text == "撤回了一条消息"

        await storage.close()

    asyncio.run(scenario())


def test_storage_messages_contacts_and_sessions(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")

        friend = Friend(uid="u_1", uin=10001, nickname="小明")
        group = Group(group_id=20002, name="测试群", member_count=3)
        await storage.contacts.upsert_friend(friend)
        await storage.contacts.upsert_group(group)

        friend_chat = FriendChat(uid="u_1", uin=10001)
        friend_message = Message(
            chat=friend_chat,
            sender_uin=10001,
            sender_uid="u_1",
            sender_name="小明",
            seq=10,
            timestamp=100,
            elements=[TextElement(text="你好")],
            from_self=True,
        )
        friend_message_2 = Message(
            chat=friend_chat,
            sender_uin=10001,
            sender_uid="u_1",
            sender_name="小明",
            seq=11,
            timestamp=110,
            elements=[TextElement(text="第二条")],
            from_self=True,
        )
        group_message = Message(
            chat=GroupChat(group_id=20002),
            sender_uin=10001,
            sender_uid="u_1",
            sender_name="我",
            seq=20,
            timestamp=200,
            elements=[TextElement(text="大家好")],
            from_self=True,
        )

        friend_id = await storage.messages.insert(friend_message)
        duplicate_id = await storage.messages.insert(friend_message)
        assert duplicate_id == friend_id
        friend_id_2 = await storage.messages.insert(friend_message_2)

        group_id = await storage.messages.insert(group_message)
        assert group_id > friend_id_2

        recent = await storage.messages.list_recent(friend_chat)
        assert [stored.message.text for stored in recent] == ["你好", "第二条"]
        assert [stored.id for stored in recent] == [friend_id, friend_id_2]
        recent_one = await storage.messages.list_recent(friend_chat, limit=1)
        assert [stored.message.text for stored in recent_one] == ["第二条"]

        assert await storage.messages.latest_id(friend_chat) == friend_id_2
        assert await storage.messages.latest_seq(friend_chat) == 11
        assert await storage.messages.list_before(friend_chat, friend_id) == []
        assert await storage.messages.has_before(friend_chat, friend_id) is False
        assert await storage.messages.has_before(friend_chat, friend_id_2) is True
        after = await storage.messages.list_after(friend_chat, friend_id)
        assert [stored.message.text for stored in after] == ["第二条"]

        await storage.messages.mark_read(friend_chat, friend_id_2)
        sessions = await storage.sessions.list_recent()
        assert [session.chat.key for session in sessions] == ["group:20002", "friend:u_1"]
        assert sessions[0].title == "测试群"
        assert sessions[0].unread_count == 1
        assert sessions[1].title == "小明"
        assert sessions[1].unread_count == 0

        assert await storage.sessions.unread_count(GroupChat(group_id=20002)) == 1

        state = UiStateStore(storage)
        await state.load_initial_state()
        assert [session.chat.key for session in state.sessions()] == ["group:20002", "friend:u_1"]
        assert [friend.uid for friend in state.friends()] == ["u_1"]
        assert [group.group_id for group in state.groups()] == [20002]

        await storage.close()

    asyncio.run(scenario())
