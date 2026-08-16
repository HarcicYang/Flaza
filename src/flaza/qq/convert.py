"""lagrange 消息事件到领域模型的转换。"""

from __future__ import annotations

from typing import Any

from lagrange.client.events.friend import FriendMessage
from lagrange.client.events.group import GroupMessage
from lagrange.client.message.elems import Text

from flaza.core.models import (
    FriendChat,
    GroupChat,
    GroupMemberRole,
    Message,
    MessageElement,
    TextElement,
)


def friend_message_to_domain(event: FriendMessage, self_uin: int) -> Message:
    """把好友消息事件转换为领域消息。

    离线补拉返回的历史里包含自己发送的消息；此时 peer 在 to_* 字段，
    否则会把自己发出去的消息归到错误会话。
    """
    from_self = event.from_uin == self_uin
    peer_uin = event.to_uin if from_self else event.from_uin
    peer_uid = event.to_uid if from_self else event.from_uid
    return Message(
        chat=FriendChat(uid=peer_uid, uin=peer_uin),
        sender_uin=event.from_uin,
        sender_uid=event.from_uid,
        sender_name=str(event.from_uin),
        seq=event.seq,
        client_seq=event.client_seq,
        rand=event.msg_id,
        timestamp=event.timestamp,
        elements=_convert_elements(event.msg_chain),
        from_self=from_self,
    )


def group_message_to_domain(event: GroupMessage, self_uin: int) -> Message:
    """把群消息事件转换为领域消息。"""
    return Message(
        chat=GroupChat(group_id=event.grp_id),
        sender_uin=event.uin,
        sender_uid=event.uid,
        sender_name=event.nickname,
        seq=event.seq,
        rand=event.rand,
        timestamp=event.time,
        elements=_convert_elements(event.msg_chain),
        from_self=event.uin == self_uin,
        sender_is_bot=event.is_bot,
        sender_role=GroupMemberRole.BOT if event.is_bot else GroupMemberRole.MEMBER,
    )


def _convert_elements(msg_chain: list[Any]) -> list[MessageElement]:
    """把 lagrange 元素转换为领域元素。

    领域模型目前只有 TextElement；At/AtAll 等具有文本预览的元素暂时按
    文本保留展示效果，其余元素取其 display 预览。后续扩展元素模型后，
    这里改为按类型精确映射。
    """
    elements: list[MessageElement] = []
    for element in msg_chain:
        if isinstance(element, Text):
            text = element.text
        else:
            text = getattr(element, "text", "") or getattr(element, "display", "") or "[未知消息]"
        elements.append(TextElement(text=text))
    return elements
