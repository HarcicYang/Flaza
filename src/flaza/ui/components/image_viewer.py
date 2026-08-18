"""全屏图片预览组件。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from neony.application.elements import Button
from neony.application.theme import stub
from neony.dom import Color, Div, DomEvent, Img, Styles

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
        self._last_x: float | None = None
        self._last_y: float | None = None

        self._image = Img(alt="")
        self._stage = Div(styles=_STAGE, container=[self._image])
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

        self._stage.on_mousedown(self._on_mousedown)

    async def open(self, preview: ImagePreview) -> None:
        self._preview = preview
        self._image.src = preview.src
        self._image.alt = preview.alt or "图片预览"
        self._fit = True
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._stage.styles = _STAGE
        self._sync_image_styles()
        self.root.styles = _OVERLAY
        await self._render()

    async def close(self) -> None:
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
        if event.ctrl_key:
            factor = 1.12 if (event.delta_y or 0) < 0 else 1 / 1.12
            await self._set_scale(self._scale * factor)
            return

        if self._fit and abs(self._scale - 1.0) < 0.01:
            return

        delta_x = _wheel_delta(event.delta_x, event.delta_mode)
        delta_y = _wheel_delta(event.delta_y, event.delta_mode)
        self._offset_x -= delta_x
        self._offset_y -= delta_y
        self._sync_image_styles()
        await self._render()

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
        if self._fit and abs(self._scale - 1.0) < 0.01:
            return
        self._dragging = True
        self._last_x = event.x
        self._last_y = event.y
        self._stage.styles = self._stage.styles.model_copy(update={"cursor": "grabbing"})

    async def _on_pointermove(self, event: DomEvent) -> None:
        if not self._dragging:
            return
        if event.movement_x is None and event.movement_y is None and (event.x is None or event.y is None):
            return

        dx = event.movement_x or 0.0
        dy = event.movement_y or 0.0
        if dx == 0 and dy == 0 and event.x is not None and event.y is not None:
            if self._last_x is not None:
                dx = event.x - self._last_x
            if self._last_y is not None:
                dy = event.y - self._last_y
        self._offset_x += dx
        self._offset_y += dy
        if event.x is not None:
            self._last_x = event.x
        if event.y is not None:
            self._last_y = event.y
        self._sync_image_styles()
        await self._render()

    async def _on_mouseup(self, _event: DomEvent) -> None:
        self._dragging = False
        self._last_x = None
        self._last_y = None
        if self.root.styles.display != "none":
            self._stage.styles = self._stage.styles.model_copy(update={"cursor": "grab"})

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
        self._image.styles = styles.model_copy(update={"transform": transform})


def _wheel_delta(value: float | None, delta_mode: int | None) -> float:
    if value is None:
        return 0.0
    if delta_mode == 1:
        return value * 16.0
    return value
