"""UiActions 纯函数测试。"""

from pathlib import Path

from flaza.ui.actions import _download_to_path, _looks_like_image


def test_looks_like_image_accepts_common_formats() -> None:
    assert _looks_like_image("/tmp/a.png")
    assert _looks_like_image("/tmp/a.JPG")
    assert _looks_like_image("/tmp/a.jpeg")
    assert _looks_like_image("/tmp/a.gif")
    assert _looks_like_image("/tmp/a.webp")
    assert _looks_like_image("/tmp/a.bmp")


def test_looks_like_image_rejects_other_files() -> None:
    assert _looks_like_image("/tmp/a.mp4") is False
    assert _looks_like_image("/tmp/a.txt") is False
    assert _looks_like_image("/tmp/a") is False


def test_download_to_path_copies_file_uri(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    destination = tmp_path / "download" / "saved.txt"
    _download_to_path(source.as_uri(), str(destination))
    assert destination.read_text(encoding="utf-8") == "hello"
