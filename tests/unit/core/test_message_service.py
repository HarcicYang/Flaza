"""消息服务测试。"""

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import override

from flaza.core.events import EventBus, MessageMediaCached
from flaza.core.models import (
    ChatTarget,
    FileElement,
    Friend,
    FriendChat,
    Group,
    GroupChat,
    GroupMember,
    ImageElement,
    Message,
    MessageElement,
    QrCodeData,
    QrCodeState,
    SelfInfo,
    SilentLoginResult,
)
from flaza.core.services import MessageService
from flaza.core.services.media_cache import MediaCache
from flaza.core.storage import Storage


class FakeQQ:
    """只实现发送消息所需的协议假实现。"""

    def __init__(self) -> None:
        self.missing_by_chat: dict[str, list[Message]] = {}
        self.calls: list[tuple[ChatTarget, int, int]] = []
        self.sent_elements: list[Sequence[MessageElement]] = []
        self.sent_files: list[tuple[str, str | None]] = []
        self.recalled: list[tuple[ChatTarget, int]] = []

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

    async def fetch_group_members(self, group_id: int) -> list[GroupMember]:
        raise NotImplementedError

    async def fetch_group_member(self, group_id: int, uid: str) -> GroupMember | None:
        raise NotImplementedError

    async def send_message(self, target: ChatTarget, elements: Sequence[MessageElement]) -> Message:
        self.sent_elements.append(elements)
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

    async def send_file(self, target: ChatTarget, path: str, filename: str | None = None) -> Message:
        self.sent_files.append((path, filename))
        return Message(
            chat=target,
            sender_uin=10001,
            sender_uid="u_self",
            sender_name="我",
            seq=2,
            timestamp=1700000000,
            elements=[FileElement(file_name=filename or Path(path).name, file_size=1)],
            from_self=True,
        )

    async def recall_message(self, target: ChatTarget, seq: int) -> None:
        self.recalled.append((target, seq))

    async def fetch_missing_messages(self, chat: ChatTarget, after_seq: int, limit: int = 500) -> list[Message]:
        self.calls.append((chat, after_seq, limit))
        return self.missing_by_chat.get(chat.key, [])


class FakeMediaCache(MediaCache):
    """返回固定 cached_path 的媒体缓存假实现。"""

    def __init__(self) -> None:
        super().__init__("/tmp")

    @override
    def has_cacheable_media(self, message: Message) -> bool:
        return any(isinstance(element, ImageElement) for element in message.elements)

    @override
    async def cache_message(self, message: Message) -> Message:
        elements = [
            element.model_copy(update={"cached_path": "/tmp/cached.png"})
            if isinstance(element, ImageElement)
            else element
            for element in message.elements
        ]
        return message.model_copy(update={"elements": elements})


def test_media_cache_schedule_updates_payload_and_publishes_event(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        bus = EventBus()
        cache = FakeMediaCache()
        service = MessageService(FakeQQ(), storage, bus, cache)

        chat = FriendChat(uid="u_1", uin=10002)
        message = Message(
            chat=chat,
            sender_uin=10002,
            sender_uid="u_1",
            seq=1,
            timestamp=100,
            elements=[ImageElement(url="https://example.com/pic.png", md5=b"m", size=1)],
        )
        await storage.messages.insert(message)

        cached_event = asyncio.Event()
        cached_messages: list[Message] = []

        async def on_cached(event: MessageMediaCached) -> None:
            cached_messages.append(event.message)
            cached_event.set()

        bus.subscribe(MessageMediaCached, on_cached)
        bus_task = asyncio.create_task(bus.run())
        try:
            service.schedule_media_cache([message])
            await asyncio.wait_for(cached_event.wait(), timeout=5)

            stored = await storage.messages.list_recent(chat)
            element = stored[0].message.elements[0]
            assert isinstance(element, ImageElement)
            assert element.cached_path == "/tmp/cached.png"
            assert cached_messages[0] == stored[0].message
        finally:
            bus_task.cancel()
            await asyncio.gather(bus_task, return_exceptions=True)
            await service.stop()
            await storage.close()

    asyncio.run(scenario())


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


def test_send_image_passes_local_path_element(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        qq = FakeQQ()
        service = MessageService(qq, storage, EventBus())

        chat = FriendChat(uid="u_1", uin=10002)
        await service.send_image(chat, "/tmp/pic.png")

        assert len(qq.sent_elements) == 1
        element = qq.sent_elements[0][0]
        assert isinstance(element, ImageElement)
        assert element.local_path == "/tmp/pic.png"

        await storage.close()

    asyncio.run(scenario())


def test_send_file_persists_file_element(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        qq = FakeQQ()
        service = MessageService(qq, storage, EventBus())

        chat = FriendChat(uid="u_1", uin=10002)
        await service.send_file(chat, "/tmp/资料.zip", "资料.zip")

        assert qq.sent_files == [("/tmp/资料.zip", "资料.zip")]
        recent = await storage.messages.list_recent(chat)
        assert len(recent) == 1
        element = recent[0].message.elements[0]
        assert isinstance(element, FileElement)
        assert element.file_name == "资料.zip"
        await storage.close()

    asyncio.run(scenario())


def test_recall_message_marks_storage_and_calls_qq(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage()
        await storage.init(tmp_path / "flaza.db")
        chat = FriendChat(uid="u_1", uin=10002)
        await storage.messages.insert(
            Message(
                chat=chat,
                sender_uin=10001,
                sender_uid="u_self",
                seq=10,
                timestamp=100,
                elements=[],
                from_self=True,
            )
        )

        qq = FakeQQ()
        service = MessageService(qq, storage, EventBus())
        await service.recall_message(chat, 10)

        assert qq.recalled == [(chat, 10)]
        recent = await storage.messages.list_recent(chat)
        assert recent[0].message.recalled is True
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
