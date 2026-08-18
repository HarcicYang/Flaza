"""全屏图片预览组件测试。"""

import asyncio

from neony.dom import DomEvent

from flaza.ui.components.image_viewer import ImagePreview, ImageViewer


def _viewer(renders: list[int]) -> ImageViewer:
    async def render() -> None:
        renders.append(1)

    return ImageViewer(render)


def _event(event_type: str = "click", value: object = None) -> DomEvent:
    return DomEvent(key="test", type=event_type, value=value, source="user")


def test_viewer_open_close_and_actual_size() -> None:
    async def scenario() -> None:
        renders: list[int] = []
        viewer = _viewer(renders)
        assert viewer.root.styles.display == "none"

        await viewer.open(ImagePreview(src="https://example.com/pic.png", width=640, height=480))
        assert viewer.root.styles.display == "flex"
        assert viewer._image.src == "https://example.com/pic.png"
        assert viewer._image.styles.transform == "translate(0.0px, 0.0px) scale(1.0)"
        assert viewer._fit is True

        await viewer._show_actual_size()
        assert viewer._fit is False
        assert viewer._image.styles.width == "640px"
        assert viewer._image.styles.height == "480px"
        assert viewer._stage.styles.justify_content == "flex-start"

        await viewer.close()
        assert viewer.root.styles.display == "none"
        assert renders

    asyncio.run(scenario())


def test_viewer_zoom_clamps_and_double_click_toggles() -> None:
    async def scenario() -> None:
        viewer = _viewer([])
        await viewer.open(ImagePreview(src="https://example.com/pic.png", width=640, height=480))

        await viewer._set_scale(10)
        assert viewer._scale == 5.0
        await viewer._set_scale(0.01)
        assert viewer._scale == 0.25

        await viewer._show_fit()
        await viewer._on_double_click(_event("dblclick"))
        assert viewer._scale == 2.0
        await viewer._on_double_click(_event("dblclick"))
        assert viewer._scale == 1.0
        assert viewer._fit is True

    asyncio.run(scenario())


def test_viewer_ctrl_wheel_zooms_and_escape_closes() -> None:
    async def scenario() -> None:
        renders: list[int] = []
        viewer = _viewer(renders)
        await viewer.open(ImagePreview(src="https://example.com/pic.png"))

        before = viewer._scale
        await viewer._on_wheel(DomEvent(key="stage", type="wheel", source="user", delta_y=-120, ctrl_key=True))
        assert viewer._scale > before

        await viewer._on_keydown(DomEvent(key="root", type="keydown", source="user", value="Escape"))
        assert viewer.root.styles.display == "none"

    asyncio.run(scenario())


def test_viewer_plain_wheel_pans_instead_of_zooming() -> None:
    async def scenario() -> None:
        viewer = _viewer([])
        await viewer.open(ImagePreview(src="https://example.com/pic.png", width=640, height=480))
        await viewer._show_actual_size()

        scale_before = viewer._scale
        await viewer._on_wheel(DomEvent(key="stage", type="wheel", source="user", delta_y=120))
        assert viewer._scale == scale_before
        assert viewer._offset_y < 0

    asyncio.run(scenario())


def test_viewer_drag_pans_image() -> None:
    async def scenario() -> None:
        viewer = _viewer([])
        await viewer.open(ImagePreview(src="https://example.com/pic.png", width=640, height=480))
        await viewer._show_actual_size()

        await viewer._on_mousedown(DomEvent(key="stage", type="mousedown", source="user", x=100, y=80))
        await viewer._on_pointermove(
            DomEvent(key="stage", type="pointermove", source="user", x=130, y=110, movement_x=30, movement_y=30)
        )
        await viewer._on_mouseup(DomEvent(key="root", type="mouseup", source="user"))

        assert viewer._offset_x == 30
        assert viewer._offset_y == 30
        assert "translate(30.0px, 30.0px)" in str(viewer._image.styles.transform)
        assert viewer._stage.styles.cursor == "grab"

    asyncio.run(scenario())


def test_viewer_actual_size_falls_back_to_fit_without_dimensions() -> None:
    async def scenario() -> None:
        viewer = _viewer([])
        await viewer.open(ImagePreview(src="https://example.com/pic.png"))
        await viewer._show_actual_size()
        assert viewer._fit is True
        assert viewer._image.styles.max_width == "100%"

    asyncio.run(scenario())


def test_viewer_zoomed_image_uses_full_canvas() -> None:
    async def scenario() -> None:
        viewer = _viewer([])
        await viewer.open(ImagePreview(src="https://example.com/pic.png", width=640, height=480))
        await viewer._show_actual_size()
        await viewer._set_scale(3.0)

        assert viewer._stage.styles.width == "100%"
        assert viewer._stage.styles.max_width is None
        assert viewer._stage.styles.max_height is None
        assert viewer._image.styles.max_width is None
        assert "scale(3.0)" in str(viewer._image.styles.transform)

    asyncio.run(scenario())
