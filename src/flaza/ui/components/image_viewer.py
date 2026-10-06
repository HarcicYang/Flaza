"""全屏图片预览组件。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from neony.application.elements import Button
from neony.application.theme import stub
from neony.dom import Animation, Color, Div, DomEvent, Img, Styles

_MIN_SCALE = 0.25
_MAX_SCALE = 5.0
_DOUBLE_CLICK_SCALE = 2.0

_OVERLAY = Styles(
    display="flex",
    position="fixed",
    top="0",
    left="0",
    right="0",
    bottom="0",
    z_index=1200,
    padding="24px",
    gap="12px",
    flex_direction="column",
    align_items="center",
    justify_content="center",
    background_color=Color(rgba=(0, 0, 0, 0.82)),
)

_SCRIM = Styles(position="absolute", top="0", left="0", right="0", bottom="0")

_TOOLBAR = Styles(
    display="flex",
    position="relative",
    gap="8px",
    align_items="center",
    justify_content="center",
    padding="6px",
    border_radius="12px",
    background_color=stub.surface,
    z_index="1",
)

_STAGE = Styles(
    display="flex",
    position="relative",
    align_items="center",
    justify_content="center",
    width="100%",
    min_height="0",
    flex_grow="1",
    overflow="hidden",
    cursor="grab",
    z_index="1",
    user_select="none",
    touch_action="none",
)

_STAGE_ACTUAL = _STAGE.model_copy(
    update={
        "align_items": "flex-start",
        "justify_content": "flex-start",
    }
)

_IMAGE_FIT = Styles(
    display="block",
    max_width="100%",
    max_height="100%",
    object_fit="contain",
    user_select="none",
    border_radius="8px",
    transition="transform 0.12s ease",
)

_IMAGE_ACTUAL = Styles(
    display="block",
    max_width=None,
    max_height=None,
    object_fit="none",
    user_select="none",
    border_radius="8px",
    transition="transform 0.12s ease",
)

_OVERLAY_IN = _OVERLAY.model_copy(
    update={"animation": Animation(name="flaza-viewer-in", duration="0.18s", timing="ease-out")}
)
_OVERLAY_OUT = _OVERLAY.model_copy(
    update={"animation": Animation(name="flaza-viewer-out", duration="0.14s", timing="ease-in")}
)
_IMAGE_IN = Animation(name="flaza-image-in", duration="0.2s", timing="ease-out")


@dataclass(frozen=True)
class ImagePreview:
    """图片预览所需的最小数据。"""

    src: str
    alt: str = ""
    width: int = 0
    height: int = 0


class ImageViewer:
    """全屏图片预览：滚轮缩放、按钮缩放、双击切换、Esc / 空白关闭。"""

    def __init__(self, render: Callable[[], Awaitable[None]]) -> None:
        self._render = render
        self._scale = 1.0
        self._fit = True
        self._preview: ImagePreview | None = None
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._dragging = False
        self._anchor_x: float | None = None
        self._anchor_y: float | None = None
        self._anchor_offset_x = 0.0
        self._anchor_offset_y = 0.0
        self._is_open = False

        self._image = Img(alt="", args={"draggable": "false"})
        self._stage = Div(styles=_STAGE, container=[self._image])
        self._stage.on_mousedown(self._on_mousedown)
        self._stage.on_wheel(self._on_wheel)
        self._stage.bubble_events = True

        zoom_out = Button("−", variant="ghost")
        zoom_in = Button("+", variant="ghost")
        actual_size = Button("1:1", variant="ghost")
        close = Button("关闭", variant="ghost")
        zoom_out.on_click(self._on_zoom_out)
        zoom_in.on_click(self._on_zoom_in)
        actual_size.on_click(self._on_toggle_actual_size)
        close.on_click(self._on_close)
        toolbar = Div(
            styles=_TOOLBAR,
            container=[zoom_out.build(), zoom_in.build(), actual_size.build(), close.build()],
        )

        scrim = Div(styles=_SCRIM)
        scrim.on_click(self._on_close)
        self._image.on_dblclick(self._on_double_click)

        self.root = Div(
            styles=_OVERLAY,
            container=[scrim, toolbar, self._stage],
        )
        self.root.styles = _OVERLAY.model_copy(update={"display": "none"})
        self.root.on_keydown(self._on_keydown)
        self.root.on_pointermove(self._on_pointermove)
        self.root.on_mouseup(self._on_mouseup)
        self.root.bubble_events = True

        # 拖拽事件由 on_mousedown/on_pointermove/on_mouseup 处理。

    @property
    def is_open(self) -> bool:
        return self._is_open

    async def open(self, preview: ImagePreview) -> None:
        self._is_open = True
        self._preview = preview
        self._image.src = preview.src
        self._image.alt = preview.alt or "图片预览"
        self._fit = True
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._stage.styles = _STAGE
        self._update_stage_cursor()
        self._sync_image_styles()
        self._image.styles = self._image.styles.model_copy(update={"animation": _IMAGE_IN})
        self.root.styles = _OVERLAY_IN
        await self._render()

    async def close(self) -> None:
        if not self._is_open:
            return
        self._is_open = False
        self._dragging = False
        self._anchor_x = None
        self._anchor_y = None
        self.root.styles = _OVERLAY_OUT
        await self._render()
        await asyncio.sleep(0.14)
        self.root.styles = _OVERLAY.model_copy(update={"display": "none"})
        await self._render()

    async def _on_close(self, _event: DomEvent) -> None:
        await self.close()

    async def _on_keydown(self, event: DomEvent) -> None:
        if event.value == "Escape":
            await self.close()

    async def _on_wheel(self, event: DomEvent) -> None:
        if event.delta_y is None and event.delta_x is None:
            return
        factor = 1.12 if (event.delta_y or 0) < 0 else 1 / 1.12
        await self._set_scale(self._scale * factor)

    async def _on_zoom_in(self, _event: DomEvent) -> None:
        await self._set_scale(self._scale * 1.25)

    async def _on_zoom_out(self, _event: DomEvent) -> None:
        await self._set_scale(self._scale / 1.25)

    async def _on_toggle_actual_size(self, _event: DomEvent) -> None:
        if self._fit:
            await self._show_actual_size()
        else:
            await self._show_fit()

    async def _on_mousedown(self, event: DomEvent) -> None:
        if event.x is None or event.y is None:
            return
        if not self._can_pan():
            return
        self._dragging = True
        self._anchor_x = event.x
        self._anchor_y = event.y
        self._anchor_offset_x = self._offset_x
        self._anchor_offset_y = self._offset_y
        self._sync_image_styles()
        self._update_stage_cursor("grabbing")
        await self._render()

    async def _on_pointermove(self, event: DomEvent) -> None:
        if not self._dragging:
            return
        if event.x is None or event.y is None or self._anchor_x is None or self._anchor_y is None:
            return

        # 每帧都由按下时的绝对锚点重算，增量事件缺失、重复或乱序时也不会漂移。
        self._offset_x = self._anchor_offset_x + event.x - self._anchor_x
        self._offset_y = self._anchor_offset_y + event.y - self._anchor_y
        self._sync_image_styles()
        await self._render()

    async def _on_mouseup(self, _event: DomEvent) -> None:
        was_dragging = self._dragging
        self._dragging = False
        self._anchor_x = None
        self._anchor_y = None
        if was_dragging:
            self._sync_image_styles()
            self._update_stage_cursor()
        await self._render()

    def _can_pan(self) -> bool:
        return not (self._fit and abs(self._scale - 1.0) < 0.01)

    def _update_stage_cursor(self, cursor: str | None = None) -> None:
        if cursor is None:
            cursor = "default" if not self._can_pan() else "grab"
        self._stage.styles = self._stage.styles.model_copy(update={"cursor": cursor})

    async def _on_double_click(self, _event: DomEvent) -> None:
        if self._fit:
            scale = 1.0 if abs(self._scale - _DOUBLE_CLICK_SCALE) < 0.01 else _DOUBLE_CLICK_SCALE
            await self._set_scale(scale)
        else:
            await self._show_fit()

    async def _show_fit(self) -> None:
        self._fit = True
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._stage.styles = _STAGE
        self._update_stage_cursor()
        self._sync_image_styles()
        await self._render()

    async def _show_actual_size(self) -> None:
        preview = self._preview
        if preview is None or preview.width <= 0 or preview.height <= 0:
            await self._show_fit()
            return
        self._fit = False
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._stage.styles = _STAGE_ACTUAL
        self._sync_image_styles()
        await self._render()

    async def _set_scale(self, scale: float) -> None:
        self._scale = max(_MIN_SCALE, min(_MAX_SCALE, scale))
        self._sync_image_styles()
        await self._render()

    def _sync_image_styles(self) -> None:
        preview = self._preview
        if self._fit or preview is None or preview.width <= 0 or preview.height <= 0:
            styles = _IMAGE_FIT
        else:
            styles = _IMAGE_ACTUAL.model_copy(
                update={
                    "width": f"{preview.width}px",
                    "height": f"{preview.height}px",
                }
            )
        transform = f"translate({self._offset_x}px, {self._offset_y}px) scale({self._scale})"
        transition = "none" if self._dragging else styles.transition
        self._image.styles = styles.model_copy(update={"transform": transform, "transition": transition})
