"""消息服务测试。"""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from flaza.core.events import EventBus
from flaza.core.models import (
    ChatTarget,
    Friend,
    FriendChat,
    Group,
    GroupChat,
    Message,
    MessageElement,
    QrCodeData,
    QrCodeState,
    SelfInfo,
    SilentLoginResult,
)
from flaza.core.services import MessageService
from flaza.core.storage import Storage


class FakeQQ:
    """只实现发送消息所需的协议假实现。"""

    def __init__(self) -> None:
        self.missing_by_chat: dict[str, list[Message]] = {}
        self.calls: list[tuple[ChatTarget, int, int]] = []

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def try_silent_login(self) -> SilentLoginResult:
        raise NotImplementedError

    async def fetch_qrcode(self) -> QrCodeData:
        raise NotImplementedError

    async def poll_qrcode(self) -> QrCodeState:
        raise NotImplementedError

    async def complete_qrcode_login(self) -> None:
        raise NotImplementedError

    async def cancel_login(self) -> None: ...

    async def get_self_info(self) -> SelfInfo:
        raise NotImplementedError

    async def fetch_friends(self) -> list[Friend]:
        raise NotImplementedError

    async def fetch_groups(self) -> list[Group]:
        raise NotImplementedError

    async def send_message(self, target: ChatTarget, elements: Sequence[MessageElement]) -> Message:
        return Message(
            chat=target,
            sender_uin=10001,
            sender_uid="u_self",
            sender_name="我",
            seq=1,
            timestamp=1700000000,
            elements=list(elements),
            from_self=True,
        )

    async def fetch_missing_messages(self, chat: ChatTarget, after_seq: int, limit: int = 500) -> list[Message]:
        self.calls.append((chat, after_seq, limit))
        return self.missing_by_chat.get(chat.key, [])


def test_send_message_marks_session_read(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        bus = EventBus()
        service = MessageService(FakeQQ(), storage, bus)

        chat = FriendChat(uid="u_1", uin=10002)
        message = await service.send_text(chat, "你好")
        assert message.from_self is True

        recent = await storage.messages.list_recent(chat)
        assert len(recent) == 1
        assert await storage.sessions.unread_count(chat) == 0

        await storage.close()

    asyncio.run(scenario())


def test_sync_offline_messages_persists_missing(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        chat = FriendChat(uid="u_1", uin=10002)
        await storage.contacts.upsert_friend(Friend(uid="u_1", uin=10002, nickname="小明"))
        await storage.messages.insert(
            Message(
                chat=chat,
                sender_uin=10002,
                sender_uid="u_1",
                sender_name="小明",
                seq=10,
                timestamp=100,
                elements=[],
            )
        )

        qq = FakeQQ()
        qq.missing_by_chat[chat.key] = [
            Message(
                chat=chat,
                sender_uin=10002,
                sender_uid="u_1",
                sender_name="小明",
                seq=11,
                timestamp=101,
                elements=[],
            ),
            Message(
                chat=chat,
                sender_uin=10002,
                sender_uid="u_1",
                sender_name="小明",
                seq=12,
                timestamp=102,
                elements=[],
            ),
        ]
        service = MessageService(qq, storage, EventBus())
        assert await service.sync_offline_messages() == 2
        assert [stored.message.seq for stored in await storage.messages.list_recent(chat)] == [10, 11, 12]
        assert qq.calls == [(chat, 10, 500)]
        await storage.close()

    asyncio.run(scenario())


def test_sync_offline_messages_includes_contacts_without_sessions(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        await storage.contacts.upsert_friend(Friend(uid="u_new", uin=20003, nickname="新朋友"))
        await storage.contacts.upsert_group(Group(group_id=30004, name="新群"))

        friend_chat = FriendChat(uid="u_new", uin=20003)
        group_chat = GroupChat(group_id=30004)
        qq = FakeQQ()
        qq.missing_by_chat[friend_chat.key] = [
            Message(chat=friend_chat, sender_uin=20003, sender_uid="u_new", seq=1, timestamp=1, elements=[])
        ]
        qq.missing_by_chat[group_chat.key] = [
            Message(chat=group_chat, sender_uin=20003, sender_uid="u_new", seq=2, timestamp=2, elements=[])
        ]

        service = MessageService(qq, storage, EventBus())
        assert await service.sync_offline_messages() == 2
        assert {call[0].key for call in qq.calls} == {friend_chat.key, group_chat.key}
        assert all(call[1] == 0 and call[2] == 50 for call in qq.calls)
        assert await storage.sessions.list_recent()
        await storage.close()

    asyncio.run(scenario())
