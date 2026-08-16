"""异步 SQLite 存储集成测试。"""

import asyncio
from pathlib import Path

from flaza.core.models import Friend, FriendChat, Group, GroupChat, Message, TextElement
from flaza.core.storage import Storage


def test_storage_messages_contacts_and_sessions(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")

        friend = Friend(uid="u_1", uin=10001, nickname="小明")
        group = Group(group_id=20002, name="测试群", member_count=3)
        await storage.contacts.upsert_friend(friend)
        await storage.contacts.upsert_group(group)

        friend_message = Message(
            chat=FriendChat(uid="u_1", uin=10001),
            sender_uin=10001,
            sender_uid="u_1",
            sender_name="小明",
            seq=10,
            timestamp=100,
            elements=[TextElement(text="你好")],
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

        group_id = await storage.messages.insert(group_message)
        assert group_id > friend_id

        recent = await storage.messages.list_recent(FriendChat(uid="u_1", uin=10001))
        assert [message.text for message in recent] == ["你好"]

        assert await storage.messages.list_before(FriendChat(uid="u_1", uin=10001), friend_id) == []
        assert await storage.messages.list_after(FriendChat(uid="u_1", uin=10001), friend_id) == []

        await storage.messages.mark_read(FriendChat(uid="u_1", uin=10001), friend_id)
        sessions = await storage.sessions.list_recent()
        assert [session.chat.key for session in sessions] == ["group:20002", "friend:u_1"]
        assert sessions[0].title == "测试群"
        assert sessions[0].unread_count == 1
        assert sessions[1].title == "小明"
        assert sessions[1].unread_count == 0

        assert await storage.sessions.unread_count(GroupChat(group_id=20002)) == 1

        await storage.close()

    asyncio.run(scenario())
