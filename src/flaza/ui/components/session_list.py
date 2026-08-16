"""会话列表组件。"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from neony.application.elements import Avatar, Badge
from neony.application.theme import stub
from neony.dom import Color, Div, DOMElement, DomEvent, Span, Styles

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
    width="100%",
    min_width="0",
    flex_shrink="0",
)

_ROW_TEXT = Styles(display="flex", flex_direction="column", gap="4px", flex_grow="1", min_width="0")

_ROW_ACTIVE = _ROW_BASE.model_copy(update={"background_color": stub.surface_raised})

_TITLE_ROW = Styles(display="flex", align_items="center", gap="8px")
_TITLE = Styles(
    font_size="14px",
    font_weight="600",
    color=stub.text_primary,
    flex_grow="1",
    min_width="0",
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
    min_width="0",
    white_space="nowrap",
    overflow="hidden",
    text_overflow="ellipsis",
)


@dataclass
class _SessionRow:
    key: str
    chat_key: str
    element: Div
    avatar: Avatar
    title: Span
    title_text: str
    time: Span
    time_text: str
    preview: Span
    preview_text: str
    preview_row: Div
    badge: Badge | None
    badge_el: DOMElement | None
    active: bool


class SessionList:
    """两行式会话列表，按 key 做增量更新。"""

    def __init__(
        self,
        state: UiStateStore,
        actions: UiActions,
        on_select: Callable[[ChatTarget], Awaitable[None]] | None = None,
    ) -> None:
        self._state = state
        self._actions = actions
        self._on_select = on_select
        self._rows: dict[str, _SessionRow] = {}
        self._ordered_keys: list[str] = []
        self._empty_el: DOMElement | None = None
        self.root = Div(key="session-list", styles=_LIST_STYLES)

    def set_sessions(self, sessions: list[Session]) -> None:
        active_chat = self._state.active_chat()
        active_key = active_chat.key if active_chat is not None else None

        if not sessions:
            self._remove_all_rows()
            self._ensure_empty()
            return

        self._remove_empty()
        incoming: dict[str, Session] = {self._row_key(session): session for session in sessions}
        desired_keys = list(incoming)

        # 先移除消失的会话，同时记录哪些是新增。
        new_rows: list[str] = []
        for key in list(self._ordered_keys):
            if key not in incoming:
                self._remove_row(key)
        for key in desired_keys:
            if key not in self._rows:
                new_rows.append(key)

        # 在正确位置插入新增行。
        for index, key in enumerate(desired_keys):
            if key in new_rows:
                row = self._build_row(incoming[key], active_key)
                self._rows[key] = row
                self._ordered_keys.insert(index, key)
                self.root.container.insert(index, row.element)

        # 更新已有行。
        for key in desired_keys:
            if key not in new_rows:
                self._update_row(self._rows[key], incoming[key], active_key)

        # 如果最终顺序不一致，移除后按目标顺序重新挂载（Neony 生成 move patch）。
        if self._ordered_keys != desired_keys:
            for row in self._rows.values():
                self._remove_element(row.element)
            self._ordered_keys = []
            for key in desired_keys:
                row = self._rows[key]
                self.root.container.append(row.element)
                self._ordered_keys.append(key)

    def _row_key(self, session: Session) -> str:
        return f"session:{session.chat.key}"

    def _build_row(self, session: Session, active_key: str | None) -> _SessionRow:
        key = self._row_key(session)
        avatar = Avatar(src=chat_avatar_url(session.chat), name=session.title, size="42px")
        title_text = session.title
        title = Span(container=[title_text], styles=_TITLE)
        time_text = _format_time(session.last_timestamp)
        time = Span(container=[time_text], styles=_TIME)
        title_row = Div(styles=_TITLE_ROW, container=[title, time])

        preview_text = session.last_text or "暂无消息"
        preview = Span(container=[preview_text], styles=_PREVIEW)
        preview_row = Div(styles=_PREVIEW_ROW, container=[preview])
        badge = None
        badge_el = None
        if session.unread_count > 0:
            badge = Badge(session.unread_count, variant="accent")
            badge_el = badge.build()
            preview_row.container.append(badge_el)

        active = session.chat.key == active_key
        row_element = Div(
            key=key,
            styles=_ROW_ACTIVE if active else _ROW_BASE,
            container=[avatar.build(), Div(styles=_ROW_TEXT, container=[title_row, preview_row])],
        )
        row_element.bubble_events = True
        row_element.on_click(self._make_click_handler(session.chat))
        return _SessionRow(
            key=key,
            chat_key=session.chat.key,
            element=row_element,
            avatar=avatar,
            title=title,
            title_text=title_text,
            time=time,
            time_text=time_text,
            preview=preview,
            preview_text=preview_text,
            preview_row=preview_row,
            badge=badge,
            badge_el=badge_el,
            active=active,
        )

    def _update_row(self, row: _SessionRow, session: Session, active_key: str | None) -> None:
        if row.title_text != session.title:
            row.title_text = session.title
            row.title.container = [session.title]
            row.avatar.name = session.title
            row.avatar.src = chat_avatar_url(session.chat)

        time_text = _format_time(session.last_timestamp)
        if row.time_text != time_text:
            row.time_text = time_text
            row.time.container = [time_text]

        preview_text = session.last_text or "暂无消息"
        if row.preview_text != preview_text:
            row.preview_text = preview_text
            row.preview.container = [preview_text]

        active = session.chat.key == active_key
        if row.active != active:
            row.active = active
            row.element.styles = _ROW_ACTIVE if active else _ROW_BASE

        if session.unread_count > 0:
            if row.badge is None:
                row.badge = Badge(session.unread_count, variant="accent")
                row.badge_el = row.badge.build()
                row.preview_row.container.append(row.badge_el)
            elif row.badge.content != session.unread_count:
                row.badge.content = session.unread_count
        elif row.badge_el is not None:
            _remove_from_container(row.preview_row.container, row.badge_el)
            row.badge = None
            row.badge_el = None

    def _remove_all_rows(self) -> None:
        for key in list(self._rows):
            self._remove_row(key)

    def _remove_row(self, key: str) -> None:
        row = self._rows.pop(key, None)
        if row is None:
            return
        with contextlib.suppress(ValueError):
            self._ordered_keys.remove(key)
        self._remove_element(row.element)

    def _remove_element(self, element: DOMElement) -> None:
        _remove_from_container(self.root.container, element)

    def _ensure_empty(self) -> None:
        if self._empty_el is not None:
            return
        self._empty_el = Span(
            container=["暂无会话"],
            styles=Styles(padding="16px 12px", color=stub.text_secondary, font_size="13px"),
            key="session-list-empty",
        )
        self.root.container.append(self._empty_el)

    def _remove_empty(self) -> None:
        if self._empty_el is None:
            return
        self._remove_element(self._empty_el)
        self._empty_el = None

    def _make_click_handler(self, chat: ChatTarget):
        async def handler(_event: DomEvent) -> None:
            if self._on_select is not None:
                await self._on_select(chat)
            else:
                await self._actions.open_chat(chat)

        return handler


def _remove_from_container(container: list[DOMElement | str], element: DOMElement) -> None:
    try:
        index = next(i for i, child in enumerate(container) if child is element)
    except StopIteration:
        return
    container.pop(index)


def _format_time(timestamp: int) -> str:
    if timestamp <= 0:
        return ""
    dt = datetime.fromtimestamp(timestamp)
    now = datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    return dt.strftime("%m-%d")
