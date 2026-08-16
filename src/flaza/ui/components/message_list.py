"""消息气泡流组件。"""

from __future__ import annotations

from neony.application.elements import Avatar, MessageBubble
from neony.application.theme import stub
from neony.dom import Div, Span, Styles

from flaza.core.models import ChatTarget, GroupChat, StoredMessage
from flaza.ui.avatars import friend_avatar_url
from flaza.ui.state import UiStateStore


class MessageList:
    """可滚动的消息流，使用 Neony MessageBubble 渲染。"""

    def __init__(self, state: UiStateStore) -> None:
        self._state = state
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

    def set_messages(self, chat: ChatTarget | None, messages: tuple[StoredMessage, ...]) -> None:
        self.root.container.clear()
        if chat is None:
            placeholder = "选择一个会话开始聊天"
        elif not messages:
            placeholder = "还没有消息，发一句打个招呼吧"
        else:
            placeholder = ""
        if placeholder:
            empty = Span(
                container=[placeholder],
                styles=Styles(
                    align_self="center",
                    margin="auto 0",
                    padding="8px 14px",
                    border_radius="12px",
                    background_color=stub.surface,
                    color=stub.text_secondary,
                    font_size="13px",
                ),
            )
            self.root.container.append(empty)
            return

        is_group = isinstance(chat, GroupChat)
        self_info = self._state.self_info()
        for stored in messages:
            message = stored.message
            if message.from_self:
                avatar = Avatar(
                    src=friend_avatar_url(self_info.uin) if self_info is not None else None,
                    name=self_info.nickname or str(self_info.uin) if self_info else "我",
                    size="36px",
                )
            else:
                avatar = Avatar(
                    src=friend_avatar_url(message.sender_uin),
                    name=message.sender_name or str(message.sender_uin),
                    size="36px",
                )
            bubble = MessageBubble(
                text=message.text,
                from_me=message.from_self,
                name=message.sender_name if is_group and not message.from_self else None,
                avatar=avatar,
            )
            self.root.container.append(bubble.build())
