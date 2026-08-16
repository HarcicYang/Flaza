"""发起新会话对话框。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from neony.application.elements import Avatar, Dialog
from neony.application.theme import stub
from neony.dom import Color, Div, DomEvent, Span, Styles

from flaza.core.models import ChatTarget, FriendChat, GroupChat
from flaza.ui.avatars import friend_avatar_url, group_avatar_url
from flaza.ui.state import UiStateStore

_SECTION = Styles(
    font_size="12px",
    font_weight="600",
    color=stub.text_secondary,
    padding="8px 4px 4px 4px",
)

_ROW = Styles(
    display="flex",
    align_items="center",
    gap="10px",
    padding="8px 10px",
    border_radius="8px",
    cursor="pointer",
    background_color=Color(name="transparent"),
)

_LIST = Styles(
    display="flex",
    flex_direction="column",
    gap="2px",
    height="320px",
    overflow_y="auto",
    overflow_x="hidden",
    min_height="0",
)


class NewChatDialog:
    """选择好友或群发起会话的模态框。"""

    def __init__(self, state: UiStateStore, on_select: Callable[[ChatTarget], Awaitable[None]]) -> None:
        content = _NewChatContent(state, on_select)
        self.dialog = Dialog(title="发起新会话", content=content.root, open=True, width="420px")


class _NewChatContent:
    """好友和群两个分区的选择内容。"""

    def __init__(self, state: UiStateStore, on_select: Callable[[ChatTarget], Awaitable[None]]) -> None:
        friends = state.friends()
        groups = state.groups()

        children: list[Div | Span] = [Span(container=["好友"], styles=_SECTION)]
        if friends:
            for friend in friends:
                children.append(
                    _contact_row(
                        Avatar(src=friend_avatar_url(friend.uin), name=friend.display_name, size="36px"),
                        friend.display_name,
                        FriendChat(uid=friend.uid, uin=friend.uin),
                        on_select,
                    )
                )
        else:
            children.append(_empty_hint("暂无好友"))

        children.append(Span(container=["群聊"], styles=_SECTION))
        if groups:
            for group in groups:
                children.append(
                    _contact_row(
                        Avatar(src=group_avatar_url(group.group_id), name=group.display_name, size="36px"),
                        group.display_name,
                        GroupChat(group_id=group.group_id),
                        on_select,
                    )
                )
        else:
            children.append(_empty_hint("暂无群聊"))

        self.root = Div(styles=_LIST, container=children)


def _contact_row(
    avatar: Avatar,
    label: str,
    chat: ChatTarget,
    on_select: Callable[[ChatTarget], Awaitable[None]],
) -> Div:
    row = Div(
        styles=_ROW,
        container=[avatar.build(), Span(container=[label], styles=Styles(font_size="14px", color=stub.text_primary))],
    )
    row.bubble_events = True

    async def handler(_event: DomEvent) -> None:
        await on_select(chat)

    row.on_click(handler)
    return row


def _empty_hint(text: str) -> Span:
    return Span(
        container=[text],
        styles=Styles(
            padding="12px 10px",
            color=stub.text_secondary,
            font_size="13px",
        ),
    )
