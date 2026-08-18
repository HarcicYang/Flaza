"""lagrange 事件到领域模型的转换测试。"""

from typing import Any

import pytest
from lagrange.client.events.friend import FriendMessage
from lagrange.client.events.group import GroupMessage
from lagrange.client.message.elems import (
    At,
    AtAll,
    Audio,
    Emoji,
    File,
    Image,
    Json,
    MarketFace,
    MulitMsg,
    Poke,
    Quote,
    Text,
    Video,
)

from flaza.core.models import (
    AtAllElement,
    AtElement,
    AudioElement,
    EmojiElement,
    FileElement,
    ForwardElement,
    GroupMemberRole,
    ImageElement,
    MarketFaceElement,
    MessageElement,
    PokeElement,
    QuoteElement,
    TextElement,
    UnknownElement,
    VideoElement,
)
from flaza.qq.convert import (
    friend_message_to_domain,
    group_message_to_domain,
    lagrange_file_to_domain,
    lagrange_image_to_domain,
)

_IMAGE = Image(
    name="pic.png",
    size=1024,
    url="https://example.com/pic.png",
    id=0,
    md5=b"md5",
    qmsg=None,
    width=640,
    height=480,
    is_emoji=False,
    display_name="[图片]",
)

_AUDIO = Audio(
    name="voice.amr",
    size=2048,
    url="https://example.com/voice.amr",
    id=0,
    md5=b"md5",
    qmsg=None,
    time=3,
    file_key="voice-key",
)

_VIDEO = Video(
    name="clip.mp4",
    size=4096,
    url="https://example.com/clip.mp4",
    id=0,
    md5=b"md5",
    qmsg=None,
    width=1280,
    height=720,
    time=8,
    file_key="video-key",
)


def _friend_event(*elements: Any) -> FriendMessage:
    return FriendMessage(
        from_uin=10001,
        from_uid="u_1",
        to_uin=10002,
        to_uid="u_2",
        seq=7,
        client_seq=8,
        msg_id=9,
        timestamp=1700000000,
        msg="",
        msg_chain=list(elements),
    )


def test_lagrange_image_to_domain_keeps_upload_fields() -> None:
    element = lagrange_image_to_domain(_IMAGE)

    assert element.url == "https://example.com/pic.png"
    assert element.name == "pic.png"
    assert element.size == 1024
    assert element.md5 == b"md5"
    assert element.width == 640
    assert element.height == 480
    assert element.display_name == "[图片]"
    assert element.local_path == ""


def test_lagrange_file_to_domain_keeps_upload_fields() -> None:
    file = File(
        file_size=2048,
        file_name="资料.zip",
        file_md5=b"file-md5",
        file_url=None,
        file_id="f1",
        file_uuid="u1",
        file_hash="h1",
    )
    element = lagrange_file_to_domain(file)

    assert element.file_name == "资料.zip"
    assert element.file_size == 2048
    assert element.file_id == "f1"
    assert element.file_uuid == "u1"
    assert element.file_hash == "h1"
    assert element.md5 == b"file-md5"


def test_friend_message_conversion() -> None:
    event = _friend_event(Text(text="你好"))

    message = friend_message_to_domain(event, self_uin=10002)
    assert message.chat.key == "friend:u_1"
    assert message.seq == 7
    assert message.client_seq == 8
    assert message.rand == 9
    assert message.from_self is False
    assert message.text == "你好"


def test_self_sent_friend_message_uses_peer_target() -> None:
    event = FriendMessage(
        from_uin=10002,
        from_uid="u_self",
        to_uin=10001,
        to_uid="u_1",
        seq=8,
        client_seq=9,
        msg_id=10,
        timestamp=1700000000,
        msg="你好",
        msg_chain=[Text(text="你好")],
    )

    message = friend_message_to_domain(event, self_uin=10002)
    assert message.chat.key == "friend:u_1"
    assert message.from_self is True


def test_group_bot_message_has_bot_role() -> None:
    event = GroupMessage(
        grp_id=20002,
        uin=10001,
        grp_name="测试群",
        nickname="机器人",
        uid="u_bot",
        seq=13,
        time=1700000000,
        rand=14,
        sub_id=1,
        sender_type=3091,
        msg="你好",
        msg_chain=[Text(text="你好")],
    )

    message = group_message_to_domain(event, self_uin=10002)
    assert message.sender_is_bot is True
    assert message.sender_role == GroupMemberRole.BOT


def test_group_message_conversion() -> None:
    event = GroupMessage(
        grp_id=20002,
        uin=10001,
        grp_name="测试群",
        nickname="小明",
        uid="u_1",
        seq=12,
        time=1700000000,
        rand=13,
        sub_id=1,
        sender_type=0,
        msg="大家好",
        msg_chain=[Text(text="大家好")],
    )

    message = group_message_to_domain(event, self_uin=10001)
    assert message.chat.key == "group:20002"
    assert message.sender_name == "小明"
    assert message.from_self is True
    assert message.text == "大家好"


@pytest.mark.parametrize(
    ("lagrange_element", "element_type", "preview_text"),
    [
        (Text(text="你好"), TextElement, "你好"),
        (At(text="@小明", uin=10001, uid="u_1"), AtElement, "@小明"),
        (AtAll(text="@全体成员"), AtAllElement, "@全体成员"),
        (_IMAGE, ImageElement, "[图片]"),
        (Emoji(id=12), EmojiElement, "[表情]"),
        (
            MarketFace(name="表情", face_id=b"aabb", tab_id=1, width=100, height=100),
            MarketFaceElement,
            "[动画表情]",
        ),
        (_AUDIO, AudioElement, "[语音]"),
        (_VIDEO, VideoElement, "[视频]"),
        (
            File(
                file_size=1024,
                file_name="资料.zip",
                file_md5=b"md5",
                file_url="https://example.com/资料.zip",
                file_id="f1",
                file_uuid=None,
                file_hash=None,
            ),
            FileElement,
            "[文件] 资料.zip",
        ),
        (Poke(id=1), PokeElement, "[戳一戳]"),
        (
            Quote(seq=1, uin=10001, timestamp=1700000000, uid="u_1", msg="原文"),
            QuoteElement,
            "[回复] 原文",
        ),
        (MulitMsg(resid="resid-1", file_name="聊天记录"), ForwardElement, "[聊天记录]"),
        (Json(raw=b"{}"), UnknownElement, "[卡片消息]"),
    ],
)
def test_non_text_elements_are_mapped_exactly(
    lagrange_element: object, element_type: type[MessageElement], preview_text: str
) -> None:
    message = friend_message_to_domain(_friend_event(lagrange_element), self_uin=10002)
    assert len(message.elements) == 1
    element = message.elements[0]
    assert type(element) is element_type
    assert element.preview_text == preview_text


def test_market_face_keeps_display_fields() -> None:
    message = friend_message_to_domain(
        _friend_event(MarketFace(name="表情", face_id=b"aabb", tab_id=2, width=120, height=120)),
        self_uin=10002,
    )
    element = message.elements[0]
    assert isinstance(element, MarketFaceElement)
    assert element.tab_id == 2
    assert element.url == "https://i.gtimg.cn/club/item/parcel/item/61/61616262/120x120.png"


def test_audio_video_file_keep_md5_for_cache_keys() -> None:
    file = File(
        file_size=1024,
        file_name="资料.zip",
        file_md5=b"file-md5",
        file_url="https://example.com/资料.zip",
        file_id="f1",
        file_uuid=None,
        file_hash=None,
    )
    message = friend_message_to_domain(_friend_event(_AUDIO, _VIDEO, file), self_uin=10002)

    audio, video, file_element = message.elements
    assert isinstance(audio, AudioElement)
    assert isinstance(video, VideoElement)
    assert isinstance(file_element, FileElement)
    assert audio.md5 == b"md5"
    assert video.md5 == b"md5"
    assert file_element.md5 == b"file-md5"


def test_unknown_element_preserves_original_kind() -> None:
    message = friend_message_to_domain(_friend_event(object()), self_uin=10002)
    element = message.elements[0]
    assert isinstance(element, UnknownElement)
    assert element.display == "[未知消息]"
    assert element.original_kind != ""


def test_mixed_chain_builds_typed_elements_and_preview() -> None:
    message = friend_message_to_domain(
        _friend_event(Text(text="看图："), _IMAGE, Poke(id=1)),
        self_uin=10002,
    )
    assert [type(element) for element in message.elements] == [TextElement, ImageElement, PokeElement]
    assert message.text == "看图：[图片][戳一戳]"
