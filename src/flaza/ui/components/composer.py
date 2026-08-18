"""消息输入与发送组件：基于 Neony RichText 的行内图文编辑器。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import mimetypes
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from neony.application.elements import Button, ImageSegment, Menu, RichText, TextSegment
from neony.application.theme import stub
from neony.dom import Color, Div, DomEvent, Styles

from flaza.ui.actions import UiActions

ErrorHandler = Callable[[str], Awaitable[None]]

_ICON_BUTTON = Styles(
    display="flex",
    align_items="center",
    justify_content="center",
    width="34px",
    height="34px",
    padding="0",
    border="none",
    border_radius="8px",
    background_color=Color(name="transparent"),
    color=stub.text_primary,
    font_size="18px",
    cursor="pointer",
    flex_shrink="0",
)

_SEND_BUTTON = _ICON_BUTTON.model_copy(
    update={
        "background_color": stub.accent,
        "color": Color(name="white"),
    }
)


class Composer:
    """行内图文编辑器。

    - 文字与图片在同一个 contenteditable 区域内自然混排；
    - 图片由 +、粘贴或拖拽加入，插入到当前光标处；
    - Enter 发送，图片可 Backspace/Delete 删除；
    - 发送时按顺序把 ``TextSegment`` / ``ImageSegment`` 交给 actions。
    """

    def __init__(
        self,
        actions: UiActions,
        render: Callable[[], Awaitable[None]],
        on_error: ErrorHandler | None = None,
    ) -> None:
        self._actions = actions
        self._render = render
        self._on_error = on_error
        # 编辑器里展示的是 data URL 缩略图；发送时要还原为本地路径。
        self._image_paths: dict[str, str] = {}

        self._editor = RichText(placeholder="输入消息…")
        self._editor.on_submit(self._on_submit)
        self._editor.on_paste_image(self._on_paste_image)
        self._editor.on_paste_files(self._on_paste_files)

        self._send_button = Button("", variant="primary", icon="➤").reset_styles(_SEND_BUTTON)
        self._plus_button = Button("", variant="ghost", icon="＋").reset_styles(_ICON_BUTTON)
        self._plus_menu = Menu(("image", "插入图片"), ("text", "新增文字"), ("file", "发送文件"))
        self._plus_menu.on_change(self._on_plus_menu_change)

        self._send_button.on_click(self._on_send)
        self._plus_button.on_click(self._on_plus_click)

        self.root = Div(
            styles=Styles(display="flex", flex_direction="column", gap="4px", padding="12px 16px"),
            container=[
                Div(
                    styles=Styles(display="flex", align_items="center", gap="8px"),
                    container=[
                        self._plus_button.build(),
                        self._editor.build(),
                        self._send_button.build(),
                    ],
                ),
                self._plus_menu.build(),
            ],
        )

    def stage_images(self, paths: list[str]) -> None:
        """把图片插入到当前光标之后（data URL 缩略图，发送时还原路径）。"""
        for path in paths:
            if not self._actions.is_image_path(path):
                continue
            if any(existing == path for existing in self._image_paths.values()):
                continue
            src = _thumb_data_url(path)
            self._image_paths[src] = path
            self._editor.insert_image(src, at_caret=True, alt=Path(path).name)

    async def _send(self) -> None:
        segments = self._editor.content()
        blocks: list[tuple[str, str]] = []
        for segment in segments:
            if isinstance(segment, TextSegment):
                text = segment.text.strip()
                if text:
                    blocks.append(("text", text))
            elif isinstance(segment, ImageSegment):
                path = self._image_paths.get(segment.src, segment.src)
                if path:
                    blocks.append(("image", path))

        if not any((kind == "text" and value.strip()) or (kind == "image" and value) for kind, value in blocks):
            return

        self._send_button.disabled = True
        try:
            await self._actions.send_composed_blocks(blocks)
            self._image_paths.clear()
            self._editor.set_content([])
        except Exception as exc:
            await self._show_error(f"发送失败：{exc}")
        finally:
            self._send_button.disabled = False
        await self._render()

    async def _send_files(self) -> None:
        self._plus_button.disabled = True
        try:
            await self._actions.pick_and_send_files()
        except Exception as exc:
            await self._show_error(f"发送失败：{exc}")
        finally:
            self._plus_button.disabled = False
        await self._render()

    async def _on_submit(self, _event: DomEvent) -> None:
        await self._send()

    async def _on_send(self, _event: DomEvent) -> None:
        await self._send()

    async def _on_plus_click(self, event: DomEvent) -> None:
        self._plus_menu.open_at(event.x or 0, event.y or 0)

    async def _on_plus_menu_change(self, event: DomEvent) -> None:
        if event.value == "image":
            paths = await self._actions.pick_images()
            if paths:
                self.stage_images(paths)
                await self._render()
        elif event.value == "text":
            self._editor.focus()
        elif event.value == "file":
            await self._send_files()

    async def _on_paste_image(self, event: DomEvent) -> None:
        paths = [path for path in (event.value or []) if self._actions.is_image_path(path)]
        if paths:
            self.stage_images(paths)
            await self._render()

    async def _on_paste_files(self, event: DomEvent) -> None:
        images: list[str] = []
        others: list[str] = []
        for file in event.paste_files or []:
            data_url = str(file.get("data_url", ""))
            if not data_url.startswith("data:"):
                continue
            path = await asyncio.to_thread(_data_url_to_tempfile, data_url, str(file.get("name", "")))
            if not path:
                continue
            if self._actions.is_image_path(path):
                images.append(path)
            else:
                others.append(path)
        if images:
            self.stage_images(images)
            await self._render()
        if others:
            await self._actions.send_files(others)

    async def _show_error(self, message: str) -> None:
        if self._on_error is not None:
            await self._on_error(message)
        else:
            await self._render()


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _thumb_data_url(path: str) -> str:
    from neony.application.urls import data_url

    return data_url(path, _sniff_image_mime(path))


def _sniff_image_mime(path: str) -> str:
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type and mime_type.startswith("image/"):
        return mime_type
    with open(path, "rb") as file:
        return _mime_from_header(file.read(16))


def _data_url_to_tempfile(data_url: str, name: str) -> str | None:
    """Decode a ``data:`` URL to a temp file; return its path or ``None``."""
    try:
        _header, payload = data_url.split(",", 1)
        content = base64.b64decode(payload)
    except (ValueError, binascii.Error):
        return None
    suffix = Path(name).suffix or _suffix_for_bytes(content)
    descriptor, path = tempfile.mkstemp(prefix="flaza-paste-", suffix=suffix)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            Path(path).unlink()
        raise
    return path


def _suffix_for_bytes(content: bytes) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }.get(_mime_from_header(content), ".bin")


def _mime_from_header(header: bytes) -> str:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return "image/gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"BM"):
        return "image/bmp"
    return "application/octet-stream"
