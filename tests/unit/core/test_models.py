"""领域模型单元测试。"""

from pydantic import TypeAdapter

from flaza.core.models import FriendChat, GroupChat, Message, TextElement


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
