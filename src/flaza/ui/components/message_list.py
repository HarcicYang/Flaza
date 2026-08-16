"""消息气泡流组件。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from neony.application.elements import Avatar, Badge, MessageBubble, NoticeBubble
from neony.application.theme import stub
from neony.dom import Div, DOMElement, Span, Styles

from flaza.core.models import ChatTarget, GroupChat, GroupMemberRole, Message, StoredMessage
from flaza.ui.avatars import friend_avatar_url
from flaza.ui.components.message_content import build_message_content
from flaza.ui.state import ChatNotice, UiStateStore

_BadgeVariant = Literal["accent", "danger", "neutral", "success"]

_ROLE_BADGE: dict[GroupMemberRole, tuple[str, _BadgeVariant]] = {
    GroupMemberRole.OWNER: ("群主", "accent"),
    GroupMemberRole.ADMIN: ("管理员", "success"),
    GroupMemberRole.BOT: ("机器人", "neutral"),
}


@dataclass
class _RenderedItem:
    key: str
    element: DOMElement
    kind: Literal["message", "recalled", "notice"]
    message: Message | None
    role: GroupMemberRole
    avatar_src: str | None


class MessageList:
    """可滚动的消息流，按 key 做增量更新。"""

    def __init__(self, state: UiStateStore) -> None:
        self._state = state
        self._items: dict[str, _RenderedItem] = {}
        self._ordered_keys: list[str] = []
        self._chat_key: str | None = None
        self._placeholder: DOMElement | None = None
        self.root = Div(
            key="message-list",
            styles=Styles(
                flex_grow="1",
                min_height="0",
                overflow_y="auto",
                padding="16px",
                display="flex",
                flex_direction="column",
                gap="10px",
            ),
        )

    def set_messages(
        self,
        chat: ChatTarget | None,
        messages: tuple[StoredMessage, ...],
        notices: tuple[ChatNotice, ...] = (),
    ) -> None:
        chat_key = chat.key if chat is not None else None
        if chat_key != self._chat_key:
            self._reset_all(chat, messages, notices)
            return

        if chat is None:
            self._ensure_placeholder("选择一个会话开始聊天")
            return

        timeline = self._build_timeline(chat, messages, notices)
        if not timeline:
            self._reset_all(chat, messages, notices)
            return

        desired_keys = [self._item_key(item) for item in timeline]
        old_keys = self._ordered_keys

        item_by_key = {self._item_key(item): item for item in timeline}

        # 最常见路径：纯尾部新增。
        if len(desired_keys) > len(old_keys) and desired_keys[: len(old_keys)] == old_keys:
            for key in desired_keys[len(old_keys) :]:
                item = item_by_key[key]
                self._append_item(key, item, chat)
            self._update_existing(timeline, chat)
            return

        # list_recent 到达 50 条上限后，最旧一条被挤出、最新一条追加。
        if len(desired_keys) == len(old_keys) and desired_keys[:-1] == old_keys[1:]:
            self._remove_first()
            self._append_item(desired_keys[-1], item_by_key[desired_keys[-1]], chat)
            self._update_existing(timeline, chat)
            return

        if desired_keys == old_keys:
            self._update_existing(timeline, chat)
            return

        self._reset_all(chat, messages, notices)

    def _reset_all(
        self,
        chat: ChatTarget | None,
        messages: tuple[StoredMessage, ...],
        notices: tuple[ChatNotice, ...],
    ) -> None:
        self.root.container.clear()
        self._items.clear()
        self._ordered_keys.clear()
        self._placeholder = None
        self._chat_key = chat.key if chat is not None else None

        if chat is None:
            self._ensure_placeholder("选择一个会话开始聊天")
            return

        timeline = self._build_timeline(chat, messages, notices)
        if not timeline:
            self._ensure_placeholder("还没有消息，发一句打个招呼吧")
            return

        for item in timeline:
            key = self._item_key(item)
            element, kind, message, role, avatar_src = self._build_item(item, chat)
            self.root.container.append(element)
            self._items[key] = _RenderedItem(
                key=key,
                element=element,
                kind=kind,
                message=message,
                role=role,
                avatar_src=avatar_src,
            )
            self._ordered_keys.append(key)

    def _ensure_placeholder(self, text: str) -> None:
        if self._placeholder is not None:
            return
        self._placeholder = Span(
            container=[text],
            styles=Styles(
                align_self="center",
                margin="auto 0",
                padding="8px 14px",
                border_radius="12px",
                background_color=stub.surface,
                color=stub.text_secondary,
                font_size="13px",
            ),
            key="message-list-placeholder",
        )
        self.root.container.append(self._placeholder)

    def _append_item(self, key: str, item: StoredMessage | ChatNotice, chat: ChatTarget) -> None:
        element, kind, message, role, avatar_src = self._build_item(item, chat)
        self.root.container.append(element)
        self._items[key] = _RenderedItem(
            key=key,
            element=element,
            kind=kind,
            message=message,
            role=role,
            avatar_src=avatar_src,
        )
        self._ordered_keys.append(key)

    def _remove_first(self) -> None:
        if not self._ordered_keys:
            return
        key = self._ordered_keys.pop(0)
        self._items.pop(key, None)
        if self.root.container:
            self.root.container.pop(0)

    def _update_existing(self, timeline: list[StoredMessage | ChatNotice], chat: ChatTarget) -> None:
        by_key = {self._item_key(item): item for item in timeline}
        for key in self._ordered_keys:
            item = by_key.get(key)
            entry = self._items.get(key)
            if item is None or entry is None:
                continue
            if isinstance(item, ChatNotice):
                continue

            stored = item
            message = stored.message
            desired_role = self._resolve_role(chat, message)
            desired_avatar = self._avatar_src(message)
            if (
                entry.kind == "message"
                and entry.message is not None
                and entry.message == message
                and entry.role == desired_role
                and entry.avatar_src == desired_avatar
            ):
                continue
            # 撤回、身份变化、头像变化：原地替换该元素。
            element, kind, new_message, role, avatar_src = self._build_item(stored, chat)
            self._replace_element(key, element)
            self._items[key] = _RenderedItem(
                key=key,
                element=element,
                kind=kind,
                message=new_message,
                role=role,
                avatar_src=avatar_src,
            )

    def _replace_element(self, key: str, element: DOMElement) -> None:
        entry = self._items.get(key)
        if entry is None:
            return
        index = self._index_of(entry.element)
        if index is None:
            return
        self.root.container.pop(index)
        self.root.container.insert(index, element)
        entry.element = element

    def _index_of(self, element: DOMElement) -> int | None:
        for index, child in enumerate(self.root.container):
            if child is element:
                return index
        return None

    def _build_item(
        self,
        item: StoredMessage | ChatNotice,
        chat: ChatTarget,
    ) -> tuple[DOMElement, Literal["message", "recalled", "notice"], Message | None, GroupMemberRole, str | None]:
        if isinstance(item, ChatNotice):
            element = NoticeBubble(item.text).build()
            element.key = f"notice:{item.key}"
            return element, "notice", None, GroupMemberRole.MEMBER, None

        message = item.message
        if message.recalled:
            element = NoticeBubble("撤回了一条消息").build()
            element.key = f"message:{item.id}"
            return element, "recalled", message, GroupMemberRole.MEMBER, None

        avatar_src = self._avatar_src(message)
        if message.from_self:
            self_info = self._state.self_info()
            avatar = Avatar(
                src=avatar_src,
                name=self_info.nickname or str(self_info.uin) if self_info else "我",
                size="36px",
            )
        else:
            avatar = Avatar(
                src=avatar_src,
                name=message.sender_name or str(message.sender_uin),
                size="36px",
            )

        role = self._resolve_role(chat, message)
        bubble = MessageBubble(
            text=message.text,
            content=build_message_content(message),
            from_me=message.from_self,
            name=message.sender_name if isinstance(chat, GroupChat) and not message.from_self else None,
            avatar=avatar,
            menu_items=[],
        )
        bubble._bubble.styles = bubble._bubble.styles.model_copy(update={"white_space": "pre-wrap"})
        if isinstance(chat, GroupChat) and not message.from_self and role is not GroupMemberRole.MEMBER:
            _MessageListHelpers._append_role_badge(bubble, role)
        element = bubble.build()
        element.key = f"message:{item.id}"
        return element, "message", message, role, avatar_src

    def _resolve_role(self, chat: ChatTarget, message: Message) -> GroupMemberRole:
        if not isinstance(chat, GroupChat) or message.from_self:
            return GroupMemberRole.MEMBER
        return self._state.group_roles().get(
            f"{chat.group_id}:{message.sender_uid}",
            message.sender_role,
        )

    def _avatar_src(self, message: Message) -> str | None:
        if message.from_self:
            self_info = self._state.self_info()
            return friend_avatar_url(self_info.uin) if self_info is not None else None
        return friend_avatar_url(message.sender_uin)

    def _item_key(self, item: StoredMessage | ChatNotice) -> str:
        if isinstance(item, ChatNotice):
            return f"notice:{item.key}"
        return f"message:{item.id}"

    def _build_timeline(
        self,
        chat: ChatTarget,
        messages: tuple[StoredMessage, ...],
        notices: tuple[ChatNotice, ...],
    ) -> list[StoredMessage | ChatNotice]:
        chat_key = chat.key
        entries: list[tuple[int, int, int, StoredMessage | ChatNotice]] = []
        for index, stored in enumerate(messages):
            entries.append((stored.message.timestamp, 0, index, stored))
        for index, notice in enumerate(notices):
            if notice.chat_key == chat_key:
                entries.append((notice.timestamp, 1, index, notice))
        entries.sort(key=_timeline_sort_key)
        return [entry[3] for entry in entries]


def _timeline_sort_key(entry: tuple[int, int, int, StoredMessage | ChatNotice]) -> tuple[int, int, int]:
    return entry[:3]


class _MessageListHelpers:
    @staticmethod
    def _append_role_badge(bubble: MessageBubble, role: GroupMemberRole) -> None:
        label, variant = _ROLE_BADGE.get(role, ("", "neutral"))
        if not label:
            return
        badge = Badge(label, variant=variant)
        name_span = bubble._name_span
        name_span.styles = name_span.styles.model_copy(update={"gap": "4px"})
        name_span.container = [
            badge.build(),
            Span(container=[bubble._name or ""]),
        ]
