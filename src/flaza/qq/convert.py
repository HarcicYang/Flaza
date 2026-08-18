"""lagrange 消息事件到领域模型的转换。"""

from __future__ import annotations

from typing import Any

from lagrange.client.events.friend import FriendMessage
from lagrange.client.events.group import GroupMessage
from lagrange.client.message import elems as lagrange_elems

from flaza.core.models import (
    AtAllElement,
    AtElement,
    AudioElement,
    EmojiElement,
    FileElement,
    ForwardElement,
    FriendChat,
    GroupChat,
    GroupMemberRole,
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

# 暂不展开的 lagrange 元素仍保留原始类型，并给出更友好的显示名。
_UNKNOWN_ELEMENT_DISPLAY = {
    "json": "[卡片消息]",
    "service": "[服务消息]",
    "raw": "[原始消息]",
    "markdown": "[Markdown 消息]",
    "keyboard": "[按钮消息]",
}


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


def lagrange_image_to_domain(element: lagrange_elems.Image) -> ImageElement:
    """把 lagrange 图片元素转换为领域模型。

    接收解析和发送上传共用同一映射，保证两种来源的字段完全一致。
    """
    return ImageElement(
        url=element.url,
        name=element.name,
        size=element.size,
        md5=element.md5,
        width=element.width,
        height=element.height,
        is_emoji=element.is_emoji,
        display_name=element.display_name,
    )


def lagrange_file_to_domain(element: lagrange_elems.File) -> FileElement:
    """把 lagrange 文件元素转换为领域模型。"""
    return FileElement(
        file_name=element.file_name,
        file_size=element.file_size,
        file_url=element.file_url,
        file_id=element.file_id,
        file_uuid=element.file_uuid,
        file_hash=element.file_hash,
        md5=element.file_md5,
    )


def _convert_elements(msg_chain: list[Any]) -> list[MessageElement]:
    """把 lagrange 元素精确映射为领域元素。

    GreyTips 是只发不收的元素，本期不提供发送能力，因此不建立领域模型；
    若未来协议版本意外出现，统一落入 UnknownElement 保留现场。
    """
    elements: list[MessageElement] = []
    for element in msg_chain:
        if isinstance(element, lagrange_elems.Text):
            elements.append(TextElement(text=element.text))
        elif isinstance(element, lagrange_elems.At):
            elements.append(AtElement(text=element.text, uin=element.uin, uid=element.uid))
        elif isinstance(element, lagrange_elems.AtAll):
            elements.append(AtAllElement(text=element.text))
        elif isinstance(element, lagrange_elems.Image):
            elements.append(lagrange_image_to_domain(element))
        elif isinstance(element, lagrange_elems.Emoji):
            # Reaction 是 Emoji 的子类，当前只保存表情 id，已足够展示占位。
            elements.append(EmojiElement(id=element.id))
        elif isinstance(element, lagrange_elems.MarketFace):
            elements.append(
                MarketFaceElement(
                    name=element.name,
                    face_id=element.face_id,
                    tab_id=element.tab_id,
                    width=element.width,
                    height=element.height,
                )
            )
        elif isinstance(element, lagrange_elems.Audio):
            elements.append(
                AudioElement(
                    url=element.url,
                    time=element.time,
                    file_key=element.file_key,
                    name=element.name,
                    size=element.size,
                    md5=element.md5,
                )
            )
        elif isinstance(element, lagrange_elems.Video):
            elements.append(
                VideoElement(
                    url=element.url,
                    name=element.name,
                    size=element.size,
                    width=element.width,
                    height=element.height,
                    time=element.time,
                    file_key=element.file_key,
                    md5=element.md5,
                )
            )
        elif isinstance(element, lagrange_elems.File):
            elements.append(lagrange_file_to_domain(element))
        elif isinstance(element, lagrange_elems.Poke):
            elements.append(PokeElement(id=element.id))
        elif isinstance(element, lagrange_elems.Quote):
            elements.append(
                QuoteElement(
                    seq=element.seq,
                    uin=element.uin,
                    timestamp=element.timestamp,
                    uid=element.uid,
                    msg=element.msg,
                )
            )
        elif isinstance(element, lagrange_elems.MulitMsg):
            elements.append(ForwardElement(resid=element.resid or "", file_name=element.file_name))
        else:
            original_kind = str(getattr(element, "type", type(element).__name__))
            display = _UNKNOWN_ELEMENT_DISPLAY.get(original_kind) or getattr(element, "display", "") or "[未知消息]"
            elements.append(UnknownElement(original_kind=original_kind, display=display))
    return elements
