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

from neony.application import icons
from neony.application.elements import Button, ImageSegment, Menu, RichText, TextSegment
from neony.application.elements.rich_text import RichSegment
from neony.application.theme import stub
from neony.dom import Button as _ButtonElem
from neony.dom import Color, Div, DOMElement, DomEvent, Span, Styles

from flaza.core.models import GroupMember, StoredMessage
from flaza.ui.actions import UiActions
from flaza.ui.components.member_picker import MemberPicker

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
    - 输入 ``@`` 自动弹出群成员选择器；
    - 回复引用时显示回复栏，发送时自动组装 ``QuoteElement``；
    - 发送时按顺序把 ``TextSegment`` / ``ImageSegment`` 交给 actions，
      并自动解析 ``@成员名`` 为 ``AtElement``。
    """

    _REPLY_BAR = Styles(
        display="flex",
        align_items="center",
        gap="8px",
        padding="6px 10px",
        border_radius="8px",
        background_color=stub.surface,
        font_size="12px",
        min_height="0",
    )
    _REPLY_LINE = Styles(
        width="3px",
        height="24px",
        border_radius="2px",
        background_color=stub.accent,
        flex_shrink="0",
    )
    _REPLY_TEXT = Styles(
        flex_grow="1",
        min_width="0",
        white_space="nowrap",
        overflow="hidden",
        text_overflow="ellipsis",
        color=stub.text_secondary,
    )
    _REPLY_CLOSE = Styles(
        display="flex",
        align_items="center",
        justify_content="center",
        width="20px",
        height="20px",
        padding="0",
        border="none",
        border_radius="4px",
        background_color=Color(name="transparent"),
        color=stub.text_secondary,
        font_size="14px",
        cursor="pointer",
        flex_shrink="0",
    )

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
        # @ 提及状态
        self._at_group_id: int | None = None
        self._at_picker: MemberPicker | None = None
        self._at_picker_el: DOMElement | None = None
        self._at_active = False  # 当前是否在 @ 输入状态
        self._at_query_start = 0  # @ 字符在文本中的位置
        # 回复引用状态
        self._reply_to: StoredMessage | None = None
        self._reply_bar: Div | None = None
        self._reply_bar_el: DOMElement | None = None

        self._editor = RichText(placeholder="输入消息…")
        self._editor.on_submit(self._on_submit)
        self._editor.on_change(self._on_editor_change)
        self._editor.on_paste_image(self._on_paste_image)
        self._editor.on_paste_files(self._on_paste_files)
        self._editor.on("input", self._on_input)
        self._editor.on("keyup", self._on_keyup)
        self._editor.on("keydown", self._on_keydown)

        self._send_button = Button("", variant="primary", icon=icons.arrow_upward).reset_styles(_SEND_BUTTON)
        self._plus_button = Button("", variant="ghost", icon=icons.add).reset_styles(_ICON_BUTTON)
        self._plus_menu = Menu(("image", "插入图片"), ("text", "新增文字"), ("file", "发送文件"))
        self._plus_menu.on_change(self._on_plus_menu_change)

        self._send_button.on_click(self._on_send)
        self._plus_button.on_click(self._on_plus_click)

        self.root = Div(
            styles=Styles(display="flex", flex_direction="column", gap="4px", padding="12px 16px", position="relative"),
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

    # ---- 回复引用 ----

    def set_reply_to(self, stored: StoredMessage | None) -> None:
        """设置或清除回复引用状态。"""
        self._reply_to = stored
        self._update_reply_bar()

    def _update_reply_bar(self) -> None:
        """更新回复引用栏的显示。"""
        if self._reply_to is None:
            if self._reply_bar_el is not None:
                with contextlib.suppress(ValueError):
                    self.root.container.remove(self._reply_bar_el)
                self._reply_bar_el = None
                self._reply_bar = None
            return

        if self._reply_bar_el is None:
            self._reply_bar = Div(styles=self._REPLY_BAR, container=[])
            self._reply_bar_el = self._reply_bar
            self.root.container.insert(0, self._reply_bar_el)

        message = self._reply_to.message
        quote_text = message.text or "原消息不可见"
        if len(quote_text) > 60:
            quote_text = quote_text[:60] + "…"
        sender = message.sender_name or str(message.sender_uin)
        label = f"回复 {sender}：{quote_text}"

        close_btn = _ButtonElem(type="button", container=["✕"], styles=self._REPLY_CLOSE)
        close_btn.on("click", self._on_reply_close)

        if self._reply_bar is not None:
            self._reply_bar.container = [
                Div(styles=self._REPLY_LINE),
                Span(container=[label], styles=self._REPLY_TEXT),
                close_btn,
            ]

    async def _on_reply_close(self, _event: DomEvent) -> None:
        """关闭回复引用栏。"""
        self.set_reply_to(None)
        await self._render()

    # ---- 群上下文 ----

    def set_group_context(
        self, group_id: int | None, members: list[GroupMember] | None = None, can_mention_all: bool = False
    ) -> None:
        """设置当前会话的群成员上下文，用于 @ 提及。

        :param group_id: 群号，None 表示当前不是群聊
        :param members: 群成员列表
        :param can_mention_all: 当前用户是否有权限 @全体成员
        """
        self._at_group_id = group_id
        self._close_picker()
        # 上一个群的 picker 必须从 DOM 移除；否则新建实例虽然状态已打开，
        # 页面上仍只有旧实例，导致补全浮层不可见。
        if self._at_picker_el is not None:
            with contextlib.suppress(ValueError):
                self.root.container.remove(self._at_picker_el)
            self._at_picker_el = None
        self._at_picker = None
        if group_id is None:
            return

        if members is None:
            members = []
        picker = MemberPicker(
            group_id,
            members,
            can_mention_all=can_mention_all,
            on_select=self._on_at_member_selected,
        )
        self._at_picker = picker
        if self._at_picker_el is None:
            self._at_picker_el = picker.root
            self.root.container.append(self._at_picker_el)

    # ---- 图片相关 ----

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

    # ---- 发送 ----

    async def _send(self) -> None:
        segments = self._editor.content()
        blocks: list[tuple[str, str]] = []
        # 收集 @ 映射：@成员名 → (uid, uin)
        at_map: dict[str, tuple[str, int, str]] = {}
        if self._at_picker is not None:
            for item in self._at_picker.all_items():
                display_key = f"@{item.display}"
                at_map[display_key] = (item.uid, item.uin, item.display)

        for segment in segments:
            if isinstance(segment, TextSegment):
                text = segment.text.strip()
                if text:
                    # 解析文本中的 @ 提及
                    resolved = self._resolve_at_mentions(text, at_map)
                    for part in resolved:
                        blocks.append(part)
            elif isinstance(segment, ImageSegment):
                path = self._image_paths.get(segment.src)
                if path is not None:
                    blocks.append(("image", path))

        if not any((kind == "text" and value.strip()) or (kind == "image" and value) for kind, value in blocks):
            return

        self._send_button.disabled = True
        try:
            # 如果有回复引用，发送到 actions 时附带 QuoteElement
            reply_to = self._reply_to
            self.set_reply_to(None)  # 先清除，避免重复
            if reply_to is not None:
                await self._actions.send_reply_message(reply_to, blocks)
            else:
                await self._actions.send_composed_blocks(blocks)
            self._image_paths.clear()
            self._editor.set_content([])
        except Exception as exc:
            await self._show_error(f"发送失败：{exc}")
        finally:
            self._send_button.disabled = False
        await self._render()

    @staticmethod
    def _resolve_at_mentions(text: str, at_map: dict[str, tuple[str, int, str]]) -> list[tuple[str, str]]:
        """解析文本中的 @ 提及，返回 (type, value) 块列表。

        将 ``@成员名`` 模式转换为 ``("at", "uid:uin:display_name")`` 块，
        其余文本按 ``("text", ...)`` 返回。
        """
        if not at_map:
            return [("text", text)]

        blocks: list[tuple[str, str]] = []
        remaining = text
        while remaining:
            # 查找下一个 @ 符号
            at_pos = remaining.find("@")
            if at_pos < 0:
                blocks.append(("text", remaining))
                break

            # @ 前的文本
            if at_pos > 0:
                blocks.append(("text", remaining[:at_pos]))

            after_at = remaining[at_pos + 1 :]
            matched = False
            for mention, (uid, uin, display_name) in sorted(at_map.items(), key=lambda x: -len(x[0])):  # type: ignore[arg-type]
                # mention 是 @成员名，去掉 @ 前缀
                name_part = mention[1:]
                if after_at.startswith(name_part) and (
                    len(after_at) == len(name_part) or not after_at[len(name_part)].isalnum()
                ):
                    blocks.append(("at", f"{uid}:{uin}:{display_name}"))
                    remaining = after_at[len(name_part) :]
                    matched = True
                    break

            if not matched:
                # 不是已知成员，保留 @ 作为普通文本
                blocks.append(("text", "@"))
                remaining = after_at

        # 合并相邻的 text 块
        merged: list[tuple[str, str]] = []
        for block in blocks:
            if merged and merged[-1][0] == "text" and block[0] == "text":
                merged[-1] = ("text", merged[-1][1] + block[1])
            else:
                merged.append(block)
        return merged

    async def _send_files(self) -> None:
        self._plus_button.disabled = True
        try:
            await self._actions.pick_and_send_files()
        except Exception as exc:
            await self._show_error(f"发送失败：{exc}")
        finally:
            self._plus_button.disabled = False
        await self._render()

    # ---- @ 检测与选择器 ----

    async def _on_input(self, event: DomEvent) -> None:
        """在 RichText 完成 DOM→模型同步后处理 @ 输入和筛选。"""
        if event.is_composing or self._at_picker is None:
            return

        full_text = _segments_to_text(self._editor.content())
        caret = self._editor.caret_position()

        # 同步 picker 状态：被外部点击关闭后重置标志，允许下次 @ 重新打开
        if self._at_active and not self._at_picker.is_open:
            self._at_active = False

        if not self._at_active:
            if caret > 0 and caret <= len(full_text) and full_text[caret - 1] == "@":
                self._at_active = True
                self._at_query_start = caret - 1
                self._show_picker()
            return

        if self._at_picker.is_open:
            query = self._get_at_query()
            # 输入空格或光标离开当前 @ 词后，补全已结束；Enter 应恢复发送。
            if any(char.isspace() for char in query):
                self._close_picker()
                return
            self._at_picker.filter(query)

    async def _on_keyup(self, _event: DomEvent) -> None:
        """保留键盘事件入口；@ 状态由 input 的同步后模型驱动。"""

    async def _on_keydown(self, event: DomEvent) -> None:
        """处理 @ 选择器中的键盘导航。"""
        if not self._at_active or not self._at_picker or not self._at_picker.is_open:
            return

        key = event.value or ""
        if key in ("ArrowDown", "ArrowUp"):
            await self._at_picker.move_selection(1 if key == "ArrowDown" else -1)
        elif key == "Enter":
            await self._at_picker.select_current()
        elif key == "Escape" or (key == "Backspace" and not self._get_at_query()):
            self._close_picker()

    async def _on_at_member_selected(self, uid: str, uin: int, name: str, display_text: str) -> None:
        """成员选择后的回调：替换编辑器中的 @query 文本。"""
        if not self._at_active:
            return

        segments = self._editor.content()
        full_text = _segments_to_text(segments)
        caret = self._editor.caret_position()

        # 找到 @ 到当前光标之间的文本
        at_pos = self._at_query_start
        if at_pos < 0 or at_pos >= len(full_text):
            self._close_picker()
            return

        # 替换 @query 为 @成员名
        new_text = full_text[:at_pos] + display_text + " " + full_text[caret:]
        new_caret = at_pos + len(display_text) + 1

        # 重建编辑器内容
        if self._at_picker is not None:
            self._at_picker.close()
        self._editor.set_content([new_text])
        self._editor.set_caret(new_caret)
        self._at_active = False

    def _get_at_query(self) -> str:
        """获取 @ 符号后的查询文本。"""
        segments = self._editor.content()
        full_text = _segments_to_text(segments)
        caret = self._editor.caret_position()
        at_pos = self._at_query_start
        if at_pos < 0 or at_pos >= len(full_text):
            return ""
        return full_text[at_pos + 1 : caret]

    def _show_picker(self) -> None:
        """在编辑器上方显示成员选择器（absolute 定位，相对父容器）。"""
        if self._at_picker is None:
            return
        query = self._get_at_query()
        self._at_picker.show_above(query=query)

    def _close_picker(self) -> None:
        """关闭成员选择器。"""
        if self._at_picker is not None:
            self._at_picker.close()
        self._at_active = False

    # ---- 事件处理器 ----

    async def _on_submit(self, _event: DomEvent) -> None:
        # 选择器打开时，Enter 用于选择高亮成员而不是发送消息
        if self._at_active and self._at_picker is not None and self._at_picker.is_open:
            await self._at_picker.select_current()
            return
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

    async def _on_editor_change(self, event: DomEvent) -> None:
        """登记 Neony 完成粘贴替换后的 data URL 图片。"""
        for segment in event.value or []:
            if not isinstance(segment, ImageSegment) or not segment.src.startswith("data:image/"):
                continue
            if segment.src in self._image_paths:
                continue
            path = await asyncio.to_thread(_data_url_to_tempfile, segment.src, segment.alt)
            if path:
                self._image_paths[segment.src] = path

    async def _on_paste_image(self, event: DomEvent) -> None:
        paths = [path for path in (event.value or []) if self._actions.is_image_path(path)]
        if paths:
            for path in paths:
                src = _thumb_data_url(path)
                self._image_paths[src] = path
            await self._render()

    async def _on_paste_files(self, event: DomEvent) -> None:
        """处理非图片文件；图片由 RichText 的 paste_image 路径统一处理。"""
        others: list[str] = []
        for file in event.paste_files or []:
            if str(file.get("type", "")).startswith("image/"):
                continue
            data_url = str(file.get("data_url", ""))
            if not data_url.startswith("data:"):
                continue
            path = await asyncio.to_thread(_data_url_to_tempfile, data_url, str(file.get("name", "")))
            if path:
                others.append(path)
        if others:
            await self._actions.send_files(others)

    async def _show_error(self, message: str) -> None:
        if self._on_error is not None:
            await self._on_error(message)
        else:
            await self._render()


def _last_text(segments: list[RichSegment]) -> str:
    """返回最后一个 TextSegment 的文本。"""
    for seg in reversed(segments):
        if isinstance(seg, TextSegment):
            return seg.text
    return ""


def _segments_to_text(segments: list[RichSegment]) -> str:
    """把所有文本段拼接为纯文本（忽略图片）。"""
    return "".join(seg.text for seg in segments if isinstance(seg, TextSegment))


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


def _bytes_to_tempfile(content: bytes, suffix: str) -> str:
    descriptor, path = tempfile.mkstemp(prefix="flaza-paste-", suffix=suffix)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            Path(path).unlink()
        raise
    return path


def _data_url_to_tempfile(data_url: str, name: str) -> str | None:
    """Decode a ``data:`` URL to a temp file; return its path or ``None``."""
    try:
        _header, payload = data_url.split(",", 1)
        content = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        return None
    suffix = Path(name).suffix or _suffix_for_bytes(content)
    return _bytes_to_tempfile(content, suffix)


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
