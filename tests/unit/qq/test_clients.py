"""LagrangeQQClient 纯函数测试。"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from lagrange.client.message.elems import Text as LagrangeText
from lagrange.info.sig import SigInfo

from flaza.config import LoginConfig, PathsConfig
from flaza.core.events import EventBus
from flaza.core.models import (
    AudioElement,
    EmojiElement,
    FriendChat,
    GroupChat,
    MarketFaceElement,
    Message,
    RequestKind,
    TextElement,
    VideoElement,
)
from flaza.qq.clients import (
    LagrangeQQClient,
    _build_signer_url,
    _fetch_message_pages,
    _page_ranges,
    _seed_login_info,
    _sync_start,
)


def test_build_signer_url_without_token() -> None:
    assert _build_signer_url("https://sign.example.com", "") == "https://sign.example.com/api/sign/sec-sign"


def test_build_signer_url_with_token() -> None:
    url = _build_signer_url("https://sign.example.com", "secret")
    assert url == "https://secret@sign.example.com/api/sign/sec-sign"


def test_build_signer_url_empty() -> None:
    assert _build_signer_url("", "") is None


def test_build_signer_url_rejects_incomplete_address() -> None:
    assert _build_signer_url("https://", "") is None


def test_sync_start() -> None:
    assert _sync_start(10, 10, 500) is None
    assert _sync_start(10, 20, 500) == 11
    assert _sync_start(0, 1000, 100) == 901


def test_page_ranges_split_and_clamp() -> None:
    assert _page_ranges(11, 120) == [(11, 60), (61, 110), (111, 120)]
    assert _page_ranges(5, 5) == [(5, 5)]
    assert _page_ranges(5, 4) == []


def test_fetch_message_pages_keeps_order_and_tolerates_failure() -> None:
    async def scenario() -> None:
        async def fetch_page(start: int, end: int) -> list[int]:
            await asyncio.sleep(0.02 if start == 1 else 0)
            if start == 51:
                raise RuntimeError("page failed")
            return [start, end]

        pages = await _fetch_message_pages("friend:u_1", [(1, 50), (51, 100), (101, 150)], fetch_page)

        assert pages == [1, 50, 101, 150]

    asyncio.run(scenario())


class _FakeRequestClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[object, ...]] = []

    async def fetch_grp_request(self, count: int = 20) -> object:
        self.calls.append(("fetch", count))
        return self.response

    async def set_grp_request(self, group_id: int, seq: int, event_type: int, action: int, reason: str = "") -> None:
        self.calls.append(("group", group_id, seq, event_type, action))

    async def set_friend_request(self, uid: str, accept: bool) -> None:
        self.calls.append(("friend", uid, accept))

    async def get_user_info(self, uid_or_uin: str | int) -> object:
        self.calls.append(("profile", uid_or_uin))
        return SimpleNamespace(
            name="小明",
            personal_sign="你好",
            country="中国",
            province="四川",
            city="成都",
            sex=SimpleNamespace(name="male"),
            age=18,
            qid="qid123",
        )

    async def friend_like(self, uid: str, count: int) -> object:
        self.calls.append(("like", uid, count))
        return SimpleNamespace(added=1, total=10)

    async def rename_grp_name(self, group_id: int, name: str) -> int:
        self.calls.append(("rename_group", group_id, name))
        return 0

    async def rename_grp_member(self, group_id: int, uid: str, name: str) -> None:
        self.calls.append(("rename_member", group_id, uid, name))

    async def kick_grp_member(self, group_id: int, uin: int, permanent: bool = False) -> None:
        self.calls.append(("kick", group_id, uin, permanent))

    async def set_grp_admin(self, group_id: int, uid: str, is_set: bool) -> None:
        self.calls.append(("admin", group_id, uid, is_set))

    async def set_grp_special_title(self, group_id: int, uid: str, title: str) -> None:
        self.calls.append(("title", group_id, uid, title))

    async def set_mute_grp(self, group_id: int, enable: bool) -> None:
        self.calls.append(("mute_all", group_id, enable))

    async def set_mute_member(self, group_id: int, uin: int, duration: int) -> None:
        self.calls.append(("mute_member", group_id, uin, duration))

    async def invite_grp_member(self, group_id: int, uids: list[str] | dict[str, int]) -> int:
        self.calls.append(("invite", group_id, tuple(uids)))
        return 0

    async def leave_grp(self, group_id: int) -> int:
        self.calls.append(("leave", group_id))
        return 0

    async def set_essence(self, group_id: int, seq: int, rand: int, is_remove: bool = False) -> None:
        self.calls.append(("essence", group_id, seq, rand, is_remove))

    async def get_forward_msg(self, res_id: str, *, is_group: bool = True) -> object:
        self.calls.append(("forward", res_id, is_group))
        return SimpleNamespace(
            messages=[
                SimpleNamespace(
                    content=[LagrangeText(text="你好")],
                    sender_uin=10001,
                    sender_nick="小明",
                    timestamp=1700000000,
                )
            ]
        )

    async def upload_grp_video(self, file: object, group_id: int, thumb: object | None = None) -> object:
        self.calls.append(("video", group_id))
        return SimpleNamespace(
            url="https://example.com/clip.mp4",
            name="clip.mp4",
            size=5,
            width=0,
            height=0,
            time=0,
            file_key="video-key",
            md5=b"video-md5",
        )

    async def upload_grp_audio(self, file: object, group_id: int) -> object:
        self.calls.append(("audio", group_id))
        return SimpleNamespace(
            url="https://example.com/voice.amr",
            time=3,
            file_key="voice-key",
            name="voice.amr",
            size=5,
            md5=b"voice-md5",
        )

    async def set_avatar(self, image: object) -> None:
        self.calls.append(("avatar",))

    async def send_grp_forward_msg(self, forward_msg: Any, group_id: int) -> int:
        texts = [
            getattr(elem, "text", "")
            for node in forward_msg.messages
            for elem in node.content
            if isinstance(elem, LagrangeText)
        ]
        self.calls.append(("forward_group", group_id, tuple(texts)))
        return 0

    async def set_nickname(self, nickname: str) -> None:
        self.calls.append(("nickname", nickname))

    async def set_bio(self, bio: str) -> None:
        self.calls.append(("bio", bio))


def test_group_request_mapping_and_response_actions() -> None:
    async def scenario() -> None:
        join = SimpleNamespace(
            seq=11,
            event_type=1,
            group=SimpleNamespace(grp_id=20001, grp_name="测试群"),
            target=SimpleNamespace(uid="u_join", name="申请人"),
            invitor=None,
            comment="你好",
        )
        invite = SimpleNamespace(
            seq=12,
            event_type=2,
            group=SimpleNamespace(grp_id=20002, grp_name="邀请群"),
            target=SimpleNamespace(uid="u_target", name=""),
            invitor=SimpleNamespace(uid="u_inv", name="邀请人"),
            comment="",
        )
        fake = _FakeRequestClient(SimpleNamespace(requests=[join, invite]))
        client = LagrangeQQClient(LoginConfig(uin=1), PathsConfig(), EventBus())
        client._client = fake  # type: ignore[assignment]

        requests = await client.fetch_group_requests()

        assert [item.kind for item in requests] == [RequestKind.GROUP_JOIN, RequestKind.GROUP_INVITE]
        assert [item.key for item in requests] == ["group-join:20001:u_join", "group-invite:20002"]
        assert requests[0].can_respond is True
        assert requests[0].seq == 11
        assert requests[1].title == "邀请人邀请你加入“邀请群”"

        await client.respond_group_request(20001, 11, 1, True)
        await client.respond_group_request(20001, 11, 1, False)
        await client.respond_friend_request("u_2", True)

        assert fake.calls == [
            ("fetch", 20),
            ("group", 20001, 11, 1, 1),
            ("group", 20001, 11, 1, 2),
            ("friend", "u_2", True),
        ]

    asyncio.run(scenario())


def test_profile_fetch_and_friend_like() -> None:
    async def scenario() -> None:
        fake = _FakeRequestClient(SimpleNamespace(requests=[]))
        client = LagrangeQQClient(LoginConfig(uin=1), PathsConfig(), EventBus())
        client._client = fake  # type: ignore[assignment]

        profile = await client.fetch_user_profile(uid="u_1", uin=10001)
        added = await client.like_friend("u_1")

        assert profile.display_name == "小明"
        assert profile.bio == "你好"
        assert profile.location == "中国 四川 成都"
        assert profile.sex == "male"
        assert profile.age == 18
        assert profile.qid == "qid123"
        assert added == 1
        assert fake.calls == [("profile", "u_1"), ("like", "u_1", 1)]

    asyncio.run(scenario())


def test_group_management_actions_delegate_and_normalize() -> None:
    async def scenario() -> None:
        fake = _FakeRequestClient(SimpleNamespace(requests=[]))
        client = LagrangeQQClient(LoginConfig(uin=1), PathsConfig(), EventBus())
        client._client = fake  # type: ignore[assignment]

        await client.rename_group(1, " 新群名 ")
        await client.rename_group_member(1, "u_2", " 小明 ")
        await client.kick_group_member(1, 10002)
        await client.set_group_admin(1, "u_2", True)
        await client.set_group_special_title(1, "u_2", " 头衔 ")
        await client.set_group_mute(1, True)
        await client.mute_group_member(1, 10002, 600)
        await client.invite_group_members(1, ["u_3", "u_4"])
        await client.leave_group(1)
        await client.set_group_essence(1, 7, 8)

        assert fake.calls == [
            ("rename_group", 1, "新群名"),
            ("rename_member", 1, "u_2", "小明"),
            ("kick", 1, 10002, False),
            ("admin", 1, "u_2", True),
            ("title", 1, "u_2", "头衔"),
            ("mute_all", 1, True),
            ("mute_member", 1, 10002, 600),
            ("invite", 1, ("u_3", "u_4")),
            ("leave", 1),
            ("essence", 1, 7, 8, False),
        ]

    asyncio.run(scenario())


def test_fetch_forward_messages_maps_nodes() -> None:
    async def scenario() -> None:
        fake = _FakeRequestClient(SimpleNamespace(requests=[]))
        client = LagrangeQQClient(LoginConfig(uin=1), PathsConfig(), EventBus())
        client._client = fake  # type: ignore[assignment]

        messages = await client.fetch_forward_messages(GroupChat(group_id=20001), "resid-1")

        assert len(messages) == 1
        assert messages[0].sender_name == "小明"
        assert messages[0].timestamp == 1700000000
        first_element = messages[0].elements[0]
        assert isinstance(first_element, TextElement)
        assert first_element.text == "你好"
        assert fake.calls == [("forward", "resid-1", True)]

    asyncio.run(scenario())


def test_prepare_outgoing_video_uploads_and_keeps_local_path(tmp_path: Path) -> None:
    async def scenario() -> None:
        fake = _FakeRequestClient(SimpleNamespace(requests=[]))
        client = LagrangeQQClient(LoginConfig(uin=1), PathsConfig(), EventBus())
        client._client = fake  # type: ignore[assignment]
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"video")

        uploaded, domain = await client._prepare_outgoing_element(
            GroupChat(group_id=20001), VideoElement(local_path=str(path))
        )

        assert uploaded.name == "clip.mp4"
        assert isinstance(domain, VideoElement)
        assert domain.cached_path == str(path)
        assert fake.calls == [("video", 20001)]

    asyncio.run(scenario())


def test_self_profile_updates_delegate_and_strip() -> None:
    async def scenario() -> None:
        fake = _FakeRequestClient(SimpleNamespace(requests=[]))
        client = LagrangeQQClient(LoginConfig(uin=1), PathsConfig(), EventBus())
        client._client = fake  # type: ignore[assignment]

        await client.set_self_nickname(" 新昵称 ")
        await client.set_self_bio(" 新签名 ")

        assert fake.calls == [("nickname", "新昵称"), ("bio", "新签名")]

    asyncio.run(scenario())


def test_prepare_outgoing_audio_uploads_and_keeps_local_path(tmp_path: Path) -> None:
    async def scenario() -> None:
        fake = _FakeRequestClient(SimpleNamespace(requests=[]))
        client = LagrangeQQClient(LoginConfig(uin=1), PathsConfig(), EventBus())
        client._client = fake  # type: ignore[assignment]
        path = tmp_path / "voice.amr"
        path.write_bytes(b"voice")

        uploaded, domain = await client._prepare_outgoing_element(
            GroupChat(group_id=20001), AudioElement(local_path=str(path))
        )

        assert uploaded.name == "voice.amr"
        assert isinstance(domain, AudioElement)
        assert domain.cached_path == str(path)
        assert fake.calls == [("audio", 20001)]

    asyncio.run(scenario())


def test_set_self_avatar_uploads_file(tmp_path: Path) -> None:
    async def scenario() -> None:
        fake = _FakeRequestClient(SimpleNamespace(requests=[]))
        client = LagrangeQQClient(LoginConfig(uin=1), PathsConfig(), EventBus())
        client._client = fake  # type: ignore[assignment]
        path = tmp_path / "avatar.png"
        path.write_bytes(b"png")

        await client.set_self_avatar(str(path))

        assert fake.calls == [("avatar",)]

    asyncio.run(scenario())


def test_forward_message_builds_node_and_sends() -> None:
    async def scenario() -> None:
        fake = _FakeRequestClient(SimpleNamespace(requests=[]))
        client = LagrangeQQClient(LoginConfig(uin=1), PathsConfig(), EventBus())
        client._client = fake  # type: ignore[assignment]
        message = Message(
            chat=GroupChat(group_id=20001),
            sender_uin=10001,
            sender_uid="u_1",
            sender_name="小明",
            seq=3,
            rand=4,
            timestamp=1700000000,
            elements=[TextElement(text="你好")],
        )

        await client.forward_messages(GroupChat(group_id=20002), [message])

        assert fake.calls == [("forward_group", 20002, ("你好",))]

    asyncio.run(scenario())


def test_prepare_outgoing_emoji_and_market_face() -> None:
    async def scenario() -> None:
        fake = _FakeRequestClient(SimpleNamespace(requests=[]))
        client = LagrangeQQClient(LoginConfig(uin=1), PathsConfig(), EventBus())
        client._client = fake  # type: ignore[assignment]

        emoji, emoji_domain = await client._prepare_outgoing_element(
            FriendChat(uid="u_1", uin=10001), EmojiElement(id=14)
        )
        face, face_domain = await client._prepare_outgoing_element(
            GroupChat(group_id=20001),
            MarketFaceElement(name="表情", face_id=b"aabb", tab_id=2, width=120, height=120),
        )

        assert emoji.id == 14
        assert emoji_domain == EmojiElement(id=14)
        assert face.face_id == b"aabb"
        assert face_domain.kind == "market_face"

    asyncio.run(scenario())


class _FakeEvents:
    def subscribe(self, _event: object, _handler: object) -> None:
        return None


class _RecordingClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.events = _FakeEvents()

    def connect(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _FakeInfoManager:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.device = SimpleNamespace(guid="ab" * 16)
        self.sig_info = SimpleNamespace(d2=b"ticket")

    def __enter__(self) -> "_FakeInfoManager":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_start_passes_network_switches_to_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def scenario() -> None:
        created: list[_RecordingClient] = []

        def factory(*args: object, **kwargs: object) -> _RecordingClient:
            client = _RecordingClient(*args, **kwargs)
            created.append(client)
            return client

        monkeypatch.setattr("flaza.qq.clients.Client", factory)
        monkeypatch.setattr("flaza.qq.clients.InfoManager", _FakeInfoManager)
        login = LoginConfig(
            uin=123,
            signer_url="https://",
            use_custom_sign_provider=False,
            use_ipv6=False,
            use_optimum=False,
        )
        paths = PathsConfig(login_info_source_dir=str(tmp_path / "missing"))
        client = LagrangeQQClient(login, paths, EventBus())

        await client.start()
        await client.stop()

        assert created[0].kwargs == {"use_ipv6": False, "use_optimum": False}

    asyncio.run(scenario())


def _write_login_info(directory: Path, uin: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    sig = SigInfo.new()
    sig.uin = uin
    (directory / "sig.bin").write_bytes(sig.dump())
    (directory / "device.json").write_text(
        '{"device_name":"test","guid":"00"*16,"kernel_version":"6.0","system_kernel":"linux"}',
        encoding="utf-8",
    )


def test_seed_login_info_copies_missing_files(tmp_path: Path) -> None:
    source = tmp_path / "lagrange-python"
    _write_login_info(source, 3672492480)
    paths = PathsConfig(
        device_info_path=str(tmp_path / "device.json"),
        sign_info_path=str(tmp_path / "sig.bin"),
        login_info_source_dir=str(source),
    )

    _seed_login_info(paths, 3672492480)

    assert (tmp_path / "device.json").is_file()
    assert (tmp_path / "sig.bin").is_file()


def test_seed_login_info_skips_other_account(tmp_path: Path) -> None:
    source = tmp_path / "lagrange-python"
    _write_login_info(source, 10001)
    paths = PathsConfig(
        device_info_path=str(tmp_path / "device.json"),
        sign_info_path=str(tmp_path / "sig.bin"),
        login_info_source_dir=str(source),
    )

    _seed_login_info(paths, 3672492480)

    assert not (tmp_path / "device.json").exists()
    assert not (tmp_path / "sig.bin").exists()


def test_seed_login_info_keeps_existing_files(tmp_path: Path) -> None:
    source = tmp_path / "lagrange-python"
    _write_login_info(source, 3672492480)
    device = tmp_path / "device.json"
    sig = tmp_path / "sig.bin"
    device.write_text("keep-device", encoding="utf-8")
    sig.write_bytes(b"keep-sig")
    paths = PathsConfig(
        device_info_path=str(device),
        sign_info_path=str(sig),
        login_info_source_dir=str(source),
    )

    _seed_login_info(paths, 3672492480)

    assert device.read_text(encoding="utf-8") == "keep-device"
    assert sig.read_bytes() == b"keep-sig"
