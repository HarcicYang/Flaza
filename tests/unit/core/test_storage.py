"""异步 SQLite 存储集成测试。"""

import asyncio
from pathlib import Path

from flaza.core.models import Friend, FriendChat, Group, GroupChat, Message, TextElement
from flaza.core.storage import Storage
from flaza.ui.state import UiStateStore


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

        assert await storage.messages.latest_id(friend_chat) == friend_id_2
        assert await storage.messages.latest_seq(friend_chat) == 11
        assert await storage.messages.list_before(friend_chat, friend_id) == []
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
