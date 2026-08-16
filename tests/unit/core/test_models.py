"""领域模型单元测试。"""

import pytest
from pydantic import TypeAdapter

from flaza.core.models import (
    AtAllElement,
    AtElement,
    AudioElement,
    EmojiElement,
    FileElement,
    ForwardElement,
    FriendChat,
    GroupChat,
    ImageElement,
    MarketFaceElement,
    Message,
    MessageElement,
    PokeElement,
    QuoteElement,
    TextElement,
    UnknownElement,
    VideoElement,
)


def test_chat_target_discriminator() -> None:
    adapter = TypeAdapter(Message)

    message = adapter.validate_python(
        {
            "chat": {"kind": "friend", "uid": "u_1", "uin": 10001},
            "sender_uin": 10001,
            "sender_uid": "u_1",
            "seq": 1,
            "timestamp": 1700000000,
            "elements": [{"kind": "text", "text": "你好"}],
            "from_self": True,
        }
    )
    assert isinstance(message.chat, FriendChat)
    assert message.text == "你好"


def test_chat_target_group_and_text_property() -> None:
    message = Message(
        chat=GroupChat(group_id=20002),
        sender_uin=10001,
        sender_uid="u_1",
        seq=2,
        timestamp=1700000001,
        elements=[TextElement(text="第一段"), TextElement(text="第二段")],
    )
    assert message.chat.key == "group:20002"
    assert message.text == "第一段第二段"


@pytest.mark.parametrize(
    ("payload", "element_type", "preview_text"),
    [
        ({"kind": "text", "text": "你好"}, TextElement, "你好"),
        ({"kind": "at", "text": "@小明", "uin": 10001, "uid": "u_1"}, AtElement, "@小明"),
        ({"kind": "at_all", "text": "@全体成员"}, AtAllElement, "@全体成员"),
        (
            {"kind": "image", "url": "https://example.com/a.png", "width": 640, "height": 480},
            ImageElement,
            "[图片]",
        ),
        ({"kind": "emoji", "id": 12}, EmojiElement, "[表情]"),
        (
            {
                "kind": "market_face",
                "name": "表情",
                "face_id": b"abc",
                "tab_id": 1,
                "width": 100,
                "height": 100,
            },
            MarketFaceElement,
            "[动画表情]",
        ),
        ({"kind": "audio", "url": "https://example.com/a.amr", "time": 3}, AudioElement, "[语音]"),
        (
            {"kind": "video", "url": "https://example.com/v.mp4", "width": 640, "height": 480, "time": 8},
            VideoElement,
            "[视频]",
        ),
        ({"kind": "file", "file_name": "资料.zip", "file_size": 1024}, FileElement, "[文件] 资料.zip"),
        ({"kind": "poke", "id": 1}, PokeElement, "[戳一戳]"),
        (
            {"kind": "quote", "seq": 1, "uin": 10001, "timestamp": 1, "msg": "原文"},
            QuoteElement,
            "[回复] 原文",
        ),
        ({"kind": "forward", "resid": "r1", "file_name": "记录"}, ForwardElement, "[聊天记录]"),
        ({"kind": "unknown", "original_kind": "json", "display": "[卡片消息]"}, UnknownElement, "[卡片消息]"),
    ],
)
def test_message_element_discriminator(
    payload: dict[str, object], element_type: type[MessageElement], preview_text: str
) -> None:
    adapter = TypeAdapter(MessageElement)
    element = adapter.validate_python(payload)
    assert type(element) is element_type
    assert element.preview_text == preview_text


def test_quote_preview_is_truncated() -> None:
    element = QuoteElement(seq=1, uin=10001, timestamp=1, msg="一" * 50)
    assert element.preview_text == f"[回复] {'一' * 30}…"


def test_market_face_url_is_derived() -> None:
    element = MarketFaceElement(name="表情", face_id=b"aabb", tab_id=1, width=100, height=100)
    assert element.url == "https://i.gtimg.cn/club/item/parcel/item/61/61616262/100x100.png"


def test_mixed_elements_preview_text() -> None:
    message = Message(
        chat=GroupChat(group_id=20002),
        sender_uin=10001,
        sender_uid="u_1",
        seq=2,
        timestamp=1700000001,
        elements=[
            TextElement(text="看图："),
            ImageElement(url="https://example.com/a.png"),
            PokeElement(id=1),
        ],
    )
    assert message.text == "看图：[图片][戳一戳]"
