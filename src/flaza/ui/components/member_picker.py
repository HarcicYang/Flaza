"""群成员选择器浮层 — 用于 @ 提及。

点击 ``@`` 后弹出，显示当前群可提及的成员列表，支持搜索过滤。
基于 Neony Menu 的 ``position: fixed`` 浮层模式。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from neony.application.theme import stub
from neony.dom import (
    Border,
    BoxShadow,
    Color,
    Div,
    DOMElement,
    DomEvent,
    Filter,
    Img,
    Shadow,
    Span,
    Styles,
    px,
)

from flaza.core.models import GroupMember, GroupMemberRole
from flaza.ui.avatars import friend_avatar_url

_AT_ALL_UID = "__at_all__"

_PANEL = Styles(
    position="fixed",
    z_index="600",
    display="none",
    flex_direction="column",
    padding="6px",
    gap="2px",
    min_width="180px",
    max_width="260px",
    max_height="320px",
    overflow="hidden",
    border_radius="8px",
    border=Border(width="1px", color=stub.border_glass),
    background_color=stub.surface_glass_bg,
    backdrop_filter=Filter(blur="20px", saturate=1.2),
    box_shadow=BoxShadow(layers=[Shadow(x=0, y=8, blur=32, color=stub.shadow)]),
)

_PANEL_OPEN = _PANEL.model_copy(
    update={
        "display": "flex",
    }
)

_PANEL_ABOVE = Styles(
    position="absolute",
    z_index="600",
    display="none",
    flex_direction="column",
    padding="6px",
    gap="2px",
    left="0",
    bottom="100%",
    min_width="180px",
    max_width="260px",
    max_height="320px",
    overflow="hidden",
    margin_bottom="4px",
    border_radius="8px",
    border=Border(width="1px", color=stub.border_glass),
    background_color=stub.surface_glass_bg,
    backdrop_filter=Filter(blur="20px", saturate=1.2),
    box_shadow=BoxShadow(layers=[Shadow(x=0, y=8, blur=32, color=stub.shadow)]),
)

_PANEL_ABOVE_OPEN = _PANEL_ABOVE.model_copy(
    update={
        "display": "flex",
    }
)

_LIST = Styles(
    display="flex",
    flex_direction="column",
    gap="2px",
    overflow_y="auto",
    overflow_x="hidden",
    min_height="0",
    flex_grow="1",
)

_EMPTY = Styles(
    padding="16px 12px",
    color=stub.text_secondary,
    font_size="13px",
    text_align="center",
)

_ROW = Styles(
    display="flex",
    align_items="center",
    gap="8px",
    padding="7px 10px",
    border_radius="6px",
    border="none",
    background_color=Color(name="transparent"),
    color=stub.text_primary,
    font_size="13px",
    text_align="left",
    cursor="pointer",
    flex_shrink="0",
)

_ROW_HOVER = _ROW.model_copy(update={"background_color": stub.surface_glass_bg})

_ROW_ACTIVE = _ROW.model_copy(update={"background_color": stub.accent_glass_bg})

_AVATAR = Styles(
    width="28px",
    height="28px",
    border_radius="50%",
    flex_shrink="0",
    object_fit="cover",
    background_color=stub.surface,
)

_AVATAR_FALLBACK = Styles(
    width="28px",
    height="28px",
    border_radius="50%",
    flex_shrink="0",
    display="flex",
    align_items="center",
    justify_content="center",
    font_size="11px",
    font_weight="600",
    color=Color(name="white"),
    overflow="hidden",
)

_NAME = Styles(
    flex_grow="1",
    min_width="0",
    white_space="nowrap",
    overflow="hidden",
    text_overflow="ellipsis",
)

_ROLE_BADGE = Styles(
    font_size="11px",
    color=stub.text_secondary,
    flex_shrink="0",
)

_SECTION = Styles(
    font_size="11px",
    font_weight="600",
    color=stub.text_secondary,
    padding="6px 10px 2px",
)


class MemberPicker:
    """浮层式群成员选择器，搜索过滤后选择 @ 提及对象。"""

    def __init__(
        self,
        group_id: int,
        members: list[GroupMember],
        *,
        can_mention_all: bool = False,
        on_select: Callable[[str, int, str, str], Awaitable[None]] | None = None,
    ) -> None:
        """
        :param group_id: 当前群号
        :param members: 群成员列表
        :param can_mention_all: 当前用户是否有权限 @全体成员
        :param on_select: 选中回调 (uid, uin, nickname, display_text)
        """
        self._group_id = group_id
        self._all_members = members
        self._can_mention_all = can_mention_all
        self._on_select = on_select
        self._filtered: list[_MemberItem] = []
        self._open = False
        self._active_index = 0
        self._row_elements: list[DOMElement] = []
        self._root = Div(styles=_PANEL, container=[])
        self._list = Div(styles=_LIST, container=[])
        self._root.container.append(self._list)
        self._root.bubble_events = True
        self._bind_outside()

        self._rebuild([])

    def show(self, x: float, y: float, query: str = "") -> None:
        """在指定视口坐标处显示，并应用查询过滤。"""
        self._root.styles = _PANEL_OPEN.model_copy(
            update={
                "left": px(round(x)),
                "top": px(round(y)),
                "bottom": None,
                "max_height": "320px",
                "max_width": "260px",
            }
        )
        self._root.args = {**self._root.args, "data-neony-outside": "true"}
        self._open = True
        self.filter(query)

    def show_above(self, query: str = "") -> None:
        """在父容器上方显示（position: absolute 相对定位）。"""
        self._root.styles = _PANEL_ABOVE_OPEN
        self._root.args = {**self._root.args, "data-neony-outside": "true"}
        self._open = True
        self.filter(query)

    def close(self) -> None:
        """隐藏选择器。"""
        if not self._open:
            return
        self._open = False
        self._root.styles = self._root.styles.model_copy(update={"display": "none"})
        self._root.args = {k: v for k, v in self._root.args.items() if k != "data-neony-outside"}

    def filter(self, query: str, *, preserve_active: bool = True) -> None:
        """按查询文本过滤成员列表并刷新 DOM。"""
        active_uid = self._active_uid() if preserve_active else None
        q = query.lower().strip()
        items: list[_MemberItem] = []

        if self._can_mention_all and (not q or "全体" in q or "all" in q):
            items.append(
                _MemberItem(
                    uid=_AT_ALL_UID,
                    uin=0,
                    name="全体成员",
                    display="@全体成员",
                    role=GroupMemberRole.OWNER,
                    avatar_bg="#e8b730",
                    avatar_text="全",
                )
            )

        for member in self._all_members:
            display = member.nickname or str(member.uin)
            if not q or q in display.lower() or q in str(member.uin):
                avatar_bg, avatar_text = _avatar_meta(member)
                items.append(
                    _MemberItem(
                        uid=member.uid,
                        uin=member.uin,
                        name=member.nickname or str(member.uin),
                        display=display,
                        role=member.role,
                        avatar_bg=avatar_bg,
                        avatar_text=avatar_text,
                    )
                )

        self._rebuild(items, active_uid=active_uid)

    def _rebuild(self, items: list[_MemberItem], *, active_uid: str | None = None) -> None:
        self._filtered = items
        self._row_elements = []
        self._active_index = next((i for i, item in enumerate(items) if item.uid == active_uid), 0)
        self._list.container.clear()
        if not items:
            self._list.container.append(Span(container=["无匹配成员"], styles=_EMPTY))
            return
        for item in items:
            row = self._build_row(item)
            self._row_elements.append(row)
            self._list.container.append(row)
        self._apply_active_styles()

    # ---- 键盘导航 ----

    async def move_selection(self, delta: int) -> None:
        """上/下移动当前高亮项。"""
        if not self._filtered:
            return
        old = self._active_index
        self._active_index = max(0, min(len(self._filtered) - 1, old + delta))
        if old != self._active_index:
            self._apply_active_styles()

    async def select_current(self) -> None:
        """选择当前高亮项（键盘 Enter 触发）。"""
        if not self._filtered or not 0 <= self._active_index < len(self._filtered):
            return
        item = self._filtered[self._active_index]
        self.close()
        if self._on_select is not None:
            display_text = f"@{item.display}"
            await self._on_select(item.uid, item.uin, item.name, display_text)

    def _apply_active_styles(self) -> None:
        """把高亮样式应用到当前行。"""
        for i, row in enumerate(self._row_elements):
            row.styles = _ROW_ACTIVE if i == self._active_index else _ROW

    def _active_uid(self) -> str | None:
        if 0 <= self._active_index < len(self._filtered):
            return self._filtered[self._active_index].uid
        return None

    def _build_row(self, item: _MemberItem) -> DOMElement:
        if item.uin > 0:
            avatar: DOMElement = Img(src=friend_avatar_url(item.uin), alt=item.display, styles=_AVATAR)
        else:
            avatar_color = Color(hex=item.avatar_bg) if item.avatar_bg.startswith("#") else Color(name=item.avatar_bg)
            avatar = Span(
                styles=_AVATAR_FALLBACK.model_copy(update={"background_color": avatar_color}),
                container=[item.avatar_text],
            )
        name = Span(container=[item.display], styles=_NAME)
        role_badge = ""
        if item.role is GroupMemberRole.OWNER:
            role_badge = "群主"
        elif item.role is GroupMemberRole.ADMIN:
            role_badge = "管理员"
        children: list[DOMElement | str] = [avatar, name]
        if role_badge:
            children.append(Span(container=[role_badge], styles=_ROLE_BADGE))
        row = Div(styles=_ROW, container=children)
        row.bubble_events = True
        row.on("click", self._make_click_handler(item))
        row.on("mouseover", self._make_hover_handler(row, _ROW_HOVER))
        row.on("mouseout", self._make_hover_handler(row, _ROW))
        return row

    def _make_hover_handler(self, row: DOMElement, style: Styles):
        async def handler(_event: DomEvent) -> None:
            row.styles = style

        return handler

    def _make_click_handler(self, item: _MemberItem):
        async def handler(_event: DomEvent) -> None:
            self.close()
            if self._on_select is not None:
                display_text = f"@{item.display}"
                await self._on_select(item.uid, item.uin, item.name, display_text)

        return handler

    def _bind_outside(self) -> None:
        """点击外部时关闭选择器（通过 Neony 的 outsideclick 事件）。"""
        self._root.on("outsideclick", self._on_outside_click)

    async def _on_outside_click(self, _event: DomEvent) -> None:
        self.close()

    @property
    def root(self) -> DOMElement:
        return self._root

    @property
    def is_open(self) -> bool:
        return self._open

    def all_items(self) -> list[_MemberItem]:
        """返回所有成员条目（不过滤），供发送时解析 @ 提及使用。"""
        items: list[_MemberItem] = []
        if self._can_mention_all:
            items.append(
                _MemberItem(
                    uid=_AT_ALL_UID,
                    uin=0,
                    name="全体成员",
                    display="全体成员",
                    role=GroupMemberRole.OWNER,
                    avatar_bg="#e8b730",
                    avatar_text="全",
                )
            )
        for member in self._all_members:
            avatar_bg, avatar_text = _avatar_meta(member)
            items.append(
                _MemberItem(
                    uid=member.uid,
                    uin=member.uin,
                    name=member.nickname or str(member.uin),
                    display=member.nickname or str(member.uin),
                    role=member.role,
                    avatar_bg=avatar_bg,
                    avatar_text=avatar_text,
                )
            )
        return items


class _MemberItem:
    """选择器内部的成员条目。"""

    def __init__(
        self,
        uid: str,
        uin: int,
        name: str,
        display: str,
        role: GroupMemberRole = GroupMemberRole.MEMBER,
        avatar_bg: str = "#888",
        avatar_text: str = "",
    ) -> None:
        self.uid = uid
        self.uin = uin
        self.name = name
        self.display = display
        self.role = role
        self.avatar_bg = avatar_bg
        self.avatar_text = avatar_text


_AVATAR_COLORS = [
    "#e67e22",
    "#2ecc71",
    "#3498db",
    "#9b59b6",
    "#1abc9c",
    "#e74c3c",
    "#f39c12",
    "#16a085",
]


def _avatar_meta(member: GroupMember) -> tuple[str, str]:
    """根据成员信息生成头像背景色和文字。"""
    name = member.nickname or str(member.uin)
    text = name[0] if name else "?"
    color = _AVATAR_COLORS[hash(member.uid) % len(_AVATAR_COLORS)]
    return color, text
