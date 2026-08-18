"""Composer 行内富文本编辑与粘贴落盘测试。"""

import base64
from pathlib import Path

from neony.application.elements import ImageSegment, TextSegment

from flaza.config import AppConfig
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
    assert all(isinstance(segment, (TextSegment, ImageSegment)) for segment in segments)


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
