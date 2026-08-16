"""lagrange 事件到领域模型的转换测试。"""

from lagrange.client.events.friend import FriendMessage
from lagrange.client.events.group import GroupMessage
from lagrange.client.message.elems import Text

from flaza.core.models import GroupMemberRole
from flaza.qq.convert import friend_message_to_domain, group_message_to_domain


def test_friend_message_conversion() -> None:
    event = FriendMessage(
        from_uin=10001,
        from_uid="u_1",
        to_uin=10002,
        to_uid="u_2",
        seq=7,
        client_seq=8,
        msg_id=9,
        timestamp=1700000000,
        msg="你好",
        msg_chain=[Text(text="你好")],
    )

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
