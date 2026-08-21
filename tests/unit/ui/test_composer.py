"""Composer 行内富文本编辑与粘贴落盘测试。"""

import asyncio
import base64
from pathlib import Path

from neony.application.elements import ImageSegment, TextSegment
from neony.dom import DomEvent

from flaza.config import AppConfig
from flaza.core.models import GroupMember
from flaza.runtime import ApplicationRuntime
from flaza.ui.components.composer import Composer, _data_url_to_tempfile, _mime_from_header


def test_mime_from_header_sniffs_common_formats() -> None:
    assert _mime_from_header(b"\x89PNG\r\n\x1a\n") == "image/png"
    assert _mime_from_header(b"\xff\xd8\xff") == "image/jpeg"
    assert _mime_from_header(b"GIF89a") == "image/gif"
    assert _mime_from_header(b"BM") == "image/bmp"
    assert _mime_from_header(b"plain") == "application/octet-stream"


def test_data_url_to_tempfile_persists_bytes() -> None:
    payload = base64.b64encode(b"\x89PNG\r\n\x1a\nhello").decode()
    path = _data_url_to_tempfile(f"data:image/png;base64,{payload}", "shot.png")
    assert path is not None
    assert path.endswith(".png")
    with open(path, "rb") as file:
        assert file.read().startswith(b"\x89PNG")


def test_composer_stages_images_inside_editor(tmp_path: Path) -> None:
    image = tmp_path / "pic.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    runtime = ApplicationRuntime(AppConfig())

    async def render() -> None:
        return None

    composer = Composer(runtime.actions, render)
    composer.stage_images([str(image), str(tmp_path / "not-image.txt")])

    segments = composer._editor.content()
    assert isinstance(segments[0], ImageSegment)
    assert segments[0].src in composer._image_paths
    assert composer._image_paths[segments[0].src] == str(image)
    assert segments[0].alt == image.name
    assert all(isinstance(segment, (TextSegment, ImageSegment)) for segment in segments)


def test_neony_pasted_data_url_is_indexed_without_replacing_editor_content(tmp_path: Path) -> None:
    async def scenario() -> None:
        composer = Composer(ApplicationRuntime(AppConfig()).actions, lambda: asyncio.sleep(0))
        src = "data:image/png;base64,iVBORw0KGgpwYXN0ZWQ="
        await composer._on_editor_change(
            DomEvent(key="editor", type="change", value=[ImageSegment(src=src, alt="pasted.png")])
        )
        assert composer._image_paths[src].endswith(".png")
        assert composer._editor.content() == []

    asyncio.run(scenario())


def test_at_completion_ignores_late_keyup_event() -> None:
    async def render() -> None:
        return None

    async def scenario() -> None:
        composer = Composer(ApplicationRuntime(AppConfig()).actions, render)
        composer.set_group_context(
            10001,
            [GroupMember(group_id=10001, uid="u_1", uin=10001, nickname="Alice")],
        )
        composer._editor.set_content(["@"])
        composer._editor.set_caret(1)
        await composer._on_input(DomEvent(key="editor", type="input"))
        assert composer._at_active is True
        assert composer._at_picker is not None
        assert composer._at_picker.is_open is True

        composer._editor.set_content(["@Al"])
        composer._editor.set_caret(3)
        await composer._on_at_member_selected("u_1", 10001, "Alice", "@Alice")
        await composer._on_input(DomEvent(key="editor", type="input"))

        assert composer._editor.content()[0].text == "@Alice "
        assert composer._at_active is False
        assert composer._at_picker is not None
        assert composer._at_picker.is_open is False

    asyncio.run(scenario())


def test_group_context_replaces_mounted_member_picker() -> None:
    async def render() -> None:
        return None

    composer = Composer(ApplicationRuntime(AppConfig()).actions, render)
    first = GroupMember(group_id=10001, uid="u_1", uin=10001, nickname="Alice")
    second = GroupMember(group_id=10002, uid="u_2", uin=10002, nickname="Bob")
    composer.set_group_context(10001, [first])
    first_root = composer._at_picker_el
    composer.set_group_context(10002, [second])

    assert first_root not in composer.root.container
    assert composer._at_picker_el is not None
    assert composer._at_picker_el in composer.root.container
    assert composer._at_picker is not None
    assert composer._at_picker.all_items()[0].uid == "u_2"


def test_input_space_closes_at_picker_before_submit() -> None:
    async def render() -> None:
        return None

    async def scenario() -> None:
        composer = Composer(ApplicationRuntime(AppConfig()).actions, render)
        composer.set_group_context(
            10001,
            [GroupMember(group_id=10001, uid="u_1", uin=10001, nickname="Alice")],
        )
        composer._editor.set_content(["@Alice "])
        composer._editor.set_caret(7)
        composer._at_active = True
        assert composer._at_picker is not None
        composer._at_picker.show_above()

        await composer._on_input(DomEvent(key="editor", type="input"))

        assert composer._at_active is False
        assert composer._at_picker.is_open is False

    asyncio.run(scenario())


def test_composer_send_blocks_rebuilds_ordered_payload(tmp_path: Path) -> None:
    image = tmp_path / "pic.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    runtime = ApplicationRuntime(AppConfig())

    async def render() -> None:
        return None

    composer = Composer(runtime.actions, render)
    composer._editor.set_content([TextSegment(text="你好"), ImageSegment(src=image.as_uri())])
    blocks = composer._editor.content()
    assert isinstance(blocks[0], TextSegment)
    assert isinstance(blocks[1], ImageSegment)
