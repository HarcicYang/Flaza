"""消息气泡流组件。"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from neony.application.elements import Avatar, Badge, MessageBubble, NoticeBubble, StickToBottom
from neony.application.theme import stub
from neony.dom import DOMElement, DomEvent, Span, Styles

from flaza.core.models import ChatTarget, FileElement, GroupChat, GroupMemberRole, Message, StoredMessage
from flaza.ui.avatars import friend_avatar_url
from flaza.ui.components.image_viewer import ImagePreview
from flaza.ui.components.message_content import build_message_content
from flaza.ui.components.reaction_picker import ReactionPicker
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
    bubble: MessageBubble | None = None


class MessageList:
    """可滚动的消息流，按 key 做增量更新。"""

    def __init__(
        self,
        state: UiStateStore,
        on_image_click: Callable[[ImagePreview], Awaitable[None]] | None = None,
        on_message_action: Callable[[str, StoredMessage], Awaitable[None]] | None = None,
        on_reaction_selected: Callable[[StoredMessage, str, int, bool], Awaitable[None]] | None = None,
        on_load_older: Callable[[], Awaitable[None]] | None = None,
        on_file_download: Callable[[FileElement], Awaitable[None]] | None = None,
    ) -> None:
        self._state = state
        self._on_image_click = on_image_click
        self._on_message_action = on_message_action
        self._on_reaction_selected = on_reaction_selected
        self._on_file_download = on_file_download
        self._loading_older = False
        self._items: dict[str, _RenderedItem] = {}
        self._ordered_keys: list[str] = []
        self._chat_key: str | None = None
        self._placeholder: DOMElement | None = None
        self._stick = StickToBottom()
        self.root = self._stick.build()
        self.root.key = "message-list"
        self.root.styles.display = "flex"
        self.root.styles.flex_direction = "column"
        self.root.styles.gap = "10px"
        self.root.styles.padding = "16px"
        self.root.bubble_events = True
        if on_load_older is not None:
            self.root.on_scroll(self._make_scroll_handler(on_load_older))

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

        # 加载更早消息：更早的 key 全部位于已有列表之前。
        # 只在 DOM 头部增量插入新节点，避免全量重建造成滚动跳动。
        if len(desired_keys) > len(old_keys) and desired_keys[len(desired_keys) - len(old_keys) :] == old_keys:
            prefix_keys = desired_keys[: len(desired_keys) - len(old_keys)]
            for index, key in enumerate(prefix_keys):
                self._prepend_item(index, key, item_by_key[key], chat)
            self._update_existing(timeline, chat)
            return

        # list_recent 到达 50 条上限后，最旧一条被挤出、最新一条追加。
        # 至少保留一个共享元素才构成“平移”，否则退化为整体替换。
        if len(desired_keys) == len(old_keys) and len(old_keys) >= 2 and desired_keys[:-1] == old_keys[1:]:
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
            element, kind, message, role, avatar_src, bubble = self._build_item(item, chat)
            self.root.container.append(element)
            self._items[key] = _RenderedItem(
                key=key,
                element=element,
                kind=kind,
                message=message,
                role=role,
                avatar_src=avatar_src,
                bubble=bubble,
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

    def _remove_placeholder(self) -> None:
        if self._placeholder is None:
            return
        with contextlib.suppress(ValueError):
            self.root.container.remove(self._placeholder)
        self._placeholder = None

    def _append_item(self, key: str, item: StoredMessage | ChatNotice, chat: ChatTarget) -> None:
        self._remove_placeholder()
        element, kind, message, role, avatar_src, bubble = self._build_item(item, chat)
        self.root.container.append(element)
        self._items[key] = _RenderedItem(
            key=key,
            element=element,
            kind=kind,
            message=message,
            role=role,
            avatar_src=avatar_src,
            bubble=bubble,
        )
        self._ordered_keys.append(key)

    def _prepend_item(self, index: int, key: str, item: StoredMessage | ChatNotice, chat: ChatTarget) -> None:
        self._remove_placeholder()
        element, kind, message, role, avatar_src, bubble = self._build_item(item, chat)
        self.root.container.insert(index, element)
        self._ordered_keys.insert(index, key)
        self._items[key] = _RenderedItem(
            key=key,
            element=element,
            kind=kind,
            message=message,
            role=role,
            avatar_src=avatar_src,
            bubble=bubble,
        )

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
            # 仅 reactions 变化时只重建内容元素，保留气泡根节点的事件处理器
            if (
                entry.kind == "message"
                and entry.message is not None
                and entry.role == desired_role
                and entry.avatar_src == desired_avatar
                and entry.message.model_copy(update={"reactions": message.reactions}) == message
            ):
                entry.message = message
                if entry.bubble is not None:
                    self_info = self._state.self_info()
                    self_uid = self_info.uid if self_info else None
                    on_reaction_click = self._make_reaction_pill_handler(stored, self_uid)
                    new_content = build_message_content(
                        message,
                        self._on_image_click,
                        self._on_file_download,
                        on_reaction_click=on_reaction_click,
                        self_uid=self_uid,
                    )
                    entry.bubble._bubble.container = [new_content]
                continue
            # 撤回、身份变化、头像变化：原地替换该元素。
            old_bubble = entry.bubble
            element, kind, new_message, role, avatar_src, bubble = self._build_item(stored, chat)
            if old_bubble is not None and bubble is not None and old_bubble._actions_shown:  # type: ignore[attr-defined]
                bubble._set_actions_visible(True)  # type: ignore[attr-defined]
            self._replace_element(key, element)
            self._items[key] = _RenderedItem(
                key=key,
                element=element,
                kind=kind,
                message=new_message,
                role=role,
                avatar_src=avatar_src,
                bubble=bubble,
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
    ) -> tuple[
        DOMElement,
        Literal["message", "recalled", "notice"],
        Message | None,
        GroupMemberRole,
        str | None,
        MessageBubble | None,
    ]:
        if isinstance(item, ChatNotice):
            element = NoticeBubble(item.text).build()
            element.key = f"notice:{item.key}"
            return element, "notice", None, GroupMemberRole.MEMBER, None, None

        message = item.message
        if message.recalled:
            element = NoticeBubble("撤回了一条消息").build()
            element.key = f"message:{item.id}"
            return element, "recalled", message, GroupMemberRole.MEMBER, None, None

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
        menu_items: list[tuple[str, str]] = []
        if message.text:
            menu_items.append(("copy", "复制文本"))
        if any(isinstance(item, FileElement) for item in message.elements):
            menu_items.append(("download", "下载文件"))
        if message.from_self:
            menu_items.append(("recall", "撤回"))
        # 回复按钮通过 hover actions 展示；表情选择器与气泡同树，保证
        # 刷新重建后仍保留右键菜单和 quick actions 的内部事件路由。
        self_info = self._state.self_info()
        self_uid = self_info.uid if self_info else None
        stored = item
        bubble = MessageBubble(
            text=message.text,
            content=build_message_content(
                message,
                self._on_image_click,
                self._on_file_download,
                on_reaction_click=self._make_reaction_pill_handler(stored, self_uid),
                self_uid=self_uid,
            ),
            from_me=message.from_self,
            name=message.sender_name if isinstance(chat, GroupChat) and not message.from_self else None,
            avatar=avatar,
            menu_items=menu_items,
            actions=[("reply", "💬"), ("reaction", "😊")],
        )
        reaction_picker = ReactionPicker(on_select=self._make_reaction_selected_handler(stored))
        bubble._col.container.append(reaction_picker.root)
        if self._on_message_action is not None:
            bubble.on_change(self._make_message_action_handler(stored))
            bubble.on_action(self._make_action_handler(stored, reaction_picker))
        bubble._bubble.styles = bubble._bubble.styles.model_copy(update={"white_space": "pre-wrap"})
        if isinstance(chat, GroupChat) and not message.from_self and role is not GroupMemberRole.MEMBER:
            _MessageListHelpers._append_role_badge(bubble, role)
        element = bubble.build()
        element.key = f"message:{item.id}"
        return element, "message", message, role, avatar_src, bubble

    def _make_message_action_handler(self, stored: StoredMessage):
        async def handler(event: DomEvent) -> None:
            if self._on_message_action is not None:
                await self._on_message_action(str(event.value), stored)

        return handler

    def _make_action_handler(self, stored: StoredMessage, reaction_picker: ReactionPicker):
        """快速动作按钮的回调（接收纯字符串值，非 DomEvent）。"""

        async def handler(value: str) -> None:
            if value == "reaction" and isinstance(stored.message.chat, GroupChat):
                reaction_picker.show_above(from_me=stored.message.from_self)
                return
            if self._on_message_action is not None:
                await self._on_message_action(value, stored)

        return handler

    def _make_reaction_selected_handler(self, stored: StoredMessage):
        async def handler(emoji: str) -> None:
            if self._on_reaction_selected is not None:
                await self._on_reaction_selected(stored, emoji, 2, False)

        return handler

    def _make_reaction_pill_handler(self, stored: StoredMessage, self_uid: str | None):
        async def handler(emoji: str) -> None:
            if self._on_reaction_selected is None:
                return
            emoji_type = 2
            is_cancel = False
            for r in stored.message.reactions:
                if r.emoji_id == emoji:
                    emoji_type = r.emoji_type
                    if self_uid is not None and self_uid in r.users:
                        is_cancel = True
                    break
            await self._on_reaction_selected(stored, emoji, emoji_type, is_cancel)

        return handler

    async def scroll_to_bottom(self, *, force: bool = False) -> None:
        """滚动到底部；``force=True`` 忽略贴底状态强制滚动。"""
        await self._stick.scroll_to_bottom(force=force)

    def _make_scroll_handler(self, callback: Callable[[], Awaitable[None]]):
        async def handler(event: DomEvent) -> None:
            if self._loading_older or not self._state.has_older_messages():
                return
            if event.scroll_top is not None and event.scroll_top > 24:
                return
            self._loading_older = True
            try:
                await callback()
            finally:
                self._loading_older = False

        return handler

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
