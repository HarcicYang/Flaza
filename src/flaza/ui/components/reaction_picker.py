"""表情回应选择器浮层 — 用于消息表情回应。

在消息气泡 hover 时点击表情按钮弹出，选择常用 Unicode emoji。
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
    Shadow,
    Span,
    Styles,
    px,
)

_PANEL = Styles(
    position="fixed",
    z_index="600",
    display="none",
    flex_direction="column",
    padding="6px",
    gap="2px",
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

_PANEL_ABOVE_RIGHT_OPEN = _PANEL_ABOVE_OPEN.model_copy(update={"left": None, "right": "0"})

_GRID = Styles(
    display="grid",
    grid_template_columns="repeat(6, 1fr)",
    gap="2px",
    padding="4px",
)

_EMOJI_BUTTON = Styles(
    display="flex",
    align_items="center",
    justify_content="center",
    width="36px",
    height="36px",
    padding="0",
    border="none",
    border_radius="6px",
    background_color=Color(name="transparent"),
    font_size="20px",
    cursor="pointer",
    transition="background-color 0.1s ease",
)

_EMOJI_BUTTON_HOVER = _EMOJI_BUTTON.model_copy(update={"background_color": stub.surface_glass_bg})

_EMOJI_BUTTON_ACTIVE = _EMOJI_BUTTON.model_copy(update={"background_color": stub.accent_glass_bg})

# 常用 Unicode emoji
_EMOJI_LIST = [
    ("😊", "笑脸"),
    ("😂", "笑哭"),
    ("❤", "爱心"),
    ("😢", "哭泣"),
    ("😮", "惊讶"),
    ("👍", "赞"),
    ("🎉", "庆祝"),
    ("🔥", "火"),
    ("💯", "满分"),
    ("👏", "鼓掌"),
    ("🙏", "拜托"),
    ("😭", "大哭"),
]


class ReactionPicker:
    """浮层式表情回应选择器。"""

    def __init__(
        self,
        on_select: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """
        :param on_select: 选中回调 (emoji_char)
        """
        self._on_select = on_select
        self._open = False
        self._root = Div(styles=_PANEL, container=[])
        self._root.bubble_events = True
        self._bind_outside()

        self._build_grid()

    def _build_grid(self) -> None:
        grid = Div(styles=_GRID, container=[])
        for emoji, label in _EMOJI_LIST:
            btn = Span(
                container=[emoji],
                styles=_EMOJI_BUTTON,
                args={"title": label, "aria-label": label, "role": "button", "tabindex": "0"},
            )
            btn.bubble_events = True
            btn.on("click", self._make_click_handler(emoji))
            btn.on("mouseover", self._make_hover_handler(btn, _EMOJI_BUTTON_HOVER))
            btn.on("mouseout", self._make_hover_handler(btn, _EMOJI_BUTTON))
            grid.container.append(btn)
        self._grid = grid
        self._root.container.append(grid)

    def _make_click_handler(self, emoji: str):
        async def handler(_event: DomEvent) -> None:
            self.close()
            if self._on_select is not None:
                await self._on_select(emoji)

        return handler

    def _make_hover_handler(self, btn: DOMElement, style: Styles):
        async def handler(_event: DomEvent) -> None:
            btn.styles = style

        return handler

    def show(self, x: float, y: float) -> None:
        """在指定视口坐标处显示。"""
        self._root.styles = _PANEL_OPEN.model_copy(
            update={
                "left": px(round(x)),
                "top": px(round(y)),
                "bottom": None,
            }
        )
        self._root.args = {**self._root.args, "data-neony-outside": "true"}
        self._open = True

    def show_above(self, *, from_me: bool = False) -> None:
        """在所属消息气泡上方显示，并按消息方向对齐。"""
        self._root.styles = _PANEL_ABOVE_RIGHT_OPEN if from_me else _PANEL_ABOVE_OPEN
        self._root.args = {**self._root.args, "data-neony-outside": "true"}
        self._open = True

    def close(self) -> None:
        """隐藏选择器。"""
        if not self._open:
            return
        self._open = False
        self._root.styles = self._root.styles.model_copy(update={"display": "none"})
        self._root.args = {k: v for k, v in self._root.args.items() if k != "data-neony-outside"}

    def _bind_outside(self) -> None:
        self._root.on("outsideclick", self._on_outside_click)

    async def _on_outside_click(self, _event: DomEvent) -> None:
        self.close()

    @property
    def root(self) -> DOMElement:
        return self._root

    @property
    def is_open(self) -> bool:
        return self._open
