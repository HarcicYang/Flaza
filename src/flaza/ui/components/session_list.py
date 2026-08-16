"""会话列表组件。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from neony.application.elements import Avatar, Badge
from neony.application.theme import stub
from neony.dom import Color, Div, DomEvent, Span, Styles

from flaza.core.models import ChatTarget, Session
from flaza.ui.actions import UiActions
from flaza.ui.avatars import chat_avatar_url
from flaza.ui.state import UiStateStore

_LIST_STYLES = Styles(
    width="260px",
    flex_shrink="0",
    display="flex",
    flex_direction="column",
    gap="2px",
    padding="8px",
    overflow_y="auto",
    overflow_x="hidden",
    min_height="0",
    border_right="1px solid var(--color-border)",
    background_color=stub.surface,
)

_ROW_BASE = Styles(
    display="flex",
    align_items="center",
    gap="10px",
    padding="10px 12px",
    border_radius="8px",
    cursor="pointer",
    background_color=Color(name="transparent"),
)

_ROW_TEXT = Styles(display="flex", flex_direction="column", gap="4px", flex_grow="1", min_width="0")

_ROW_ACTIVE = _ROW_BASE.model_copy(update={"background_color": stub.surface_raised})

_TITLE_ROW = Styles(display="flex", align_items="center", gap="8px")
_TITLE = Styles(
    font_size="14px",
    font_weight="600",
    color=stub.text_primary,
    flex_grow="1",
    white_space="nowrap",
    overflow="hidden",
    text_overflow="ellipsis",
)
_TIME = Styles(font_size="11px", color=stub.text_secondary, flex_shrink="0")
_PREVIEW_ROW = Styles(display="flex", align_items="center", gap="8px")
_PREVIEW = Styles(
    font_size="12px",
    color=stub.text_secondary,
    flex_grow="1",
    white_space="nowrap",
    overflow="hidden",
    text_overflow="ellipsis",
)


class SessionList:
    """两行式会话列表。"""

    def __init__(
        self,
        state: UiStateStore,
        actions: UiActions,
        on_select: Callable[[ChatTarget], Awaitable[None]] | None = None,
    ) -> None:
        self._state = state
        self._actions = actions
        self._on_select = on_select
        self.root = Div(key="session-list", styles=_LIST_STYLES)

    def set_sessions(self, sessions: list[Session]) -> None:
        self.root.container.clear()
        if not sessions:
            empty = Span(
                container=["暂无会话"], styles=Styles(padding="16px 12px", color=stub.text_secondary, font_size="13px")
            )
            self.root.container.append(empty)
            return

        active_chat = self._state.active_chat()
        active_key = active_chat.key if active_chat is not None else None
        for session in sessions:
            self.root.container.append(self._build_row(session, active_key))

    def _build_row(self, session: Session, active_key: str | None) -> Div:
        avatar = Avatar(src=chat_avatar_url(session.chat), name=session.title, size="42px")
        title = Span(container=[session.title], styles=_TITLE)
        last_time = Span(container=[_format_time(session.last_timestamp)], styles=_TIME)
        title_row = Div(styles=_TITLE_ROW, container=[title, last_time])

        preview = Span(container=[session.last_text or "暂无消息"], styles=_PREVIEW)
        preview_row = Div(styles=_PREVIEW_ROW, container=[preview])
        if session.unread_count > 0:
            badge = Badge(session.unread_count, variant="accent").build()
            preview_row.container.append(badge)

        row = Div(
            key=f"session:{session.chat.key}",
            styles=_ROW_ACTIVE if session.chat.key == active_key else _ROW_BASE,
            container=[avatar.build(), Div(styles=_ROW_TEXT, container=[title_row, preview_row])],
        )
        row.bubble_events = True
        row.on_click(self._make_click_handler(session))
        return row

    def _make_click_handler(self, session: Session):
        async def handler(_event: DomEvent) -> None:
            if self._on_select is not None:
                await self._on_select(session.chat)
            else:
                await self._actions.open_chat(session.chat)

        return handler


def _format_time(timestamp: int) -> str:
    if timestamp <= 0:
        return ""
    dt = datetime.fromtimestamp(timestamp)
    now = datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    return dt.strftime("%m-%d")
