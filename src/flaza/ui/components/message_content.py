"""消息元素到 Neony DOM 的渲染器。"""

from __future__ import annotations

import mimetypes
from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from neony.application.elements import Button
from neony.application.theme import stub
from neony.application.urls import data_url, file_url
from neony.dom import Anchor, Audio, Border, Color, Div, DOMElement, DomEvent, Img, Span, Styles, Video

from flaza.core.models import (
    AtAllElement,
    AtElement,
    AudioElement,
    EmojiElement,
    FileElement,
    ForwardElement,
    ImageElement,
    MarketFaceElement,
    Message,
    MessageElement,
    PokeElement,
    QuoteElement,
    TextElement,
    UnknownElement,
    VideoElement,
)
from flaza.ui.components.image_viewer import ImagePreview

ImageClickHandler = Callable[[ImagePreview], Awaitable[None]]
FileDownloadHandler = Callable[[FileElement], Awaitable[None]]

_INLINE_ELEMENT_TYPES = (TextElement, AtElement, AtAllElement)

_CONTENT = Styles(
    display="flex",
    flex_direction="column",
    align_items="flex-start",
    gap="6px",
    max_width="100%",
    white_space="pre-wrap",
)

_TEXT = Styles(white_space="pre-wrap", word_break="break-word")
_INLINE_GROUP = Styles(max_width="100%", white_space="pre-wrap", word_break="break-word")
_AT_COLOR_OTHER = Color(hex="#2f7fd1")
_AT_COLOR_ME = Color(hex="#b9dcff")

_IMAGE = Styles(
    display="block",
    max_width="100%",
    max_height="320px",
    border_radius="8px",
    object_fit="contain",
    flex_shrink="0",
    align_self="flex-start",
)
_AUDIO = Styles(
    display="block",
    width="100%",
    flex_shrink="0",
    align_self="stretch",
)
_VIDEO = Styles(
    display="block",
    max_width="100%",
    max_height="360px",
    border_radius="8px",
    object_fit="contain",
    flex_shrink="0",
    align_self="flex-start",
)

_CARD = Styles(
    display="inline-flex",
    flex_direction="column",
    gap="2px",
    max_width="100%",
    padding="7px 10px",
    border_radius="8px",
    border=Border(width="1px", color=Color(name="currentColor")),
    opacity="0.9",
)
_CARD_TITLE = Styles(font_size="13px", font_weight="600", word_break="break-word")
_CARD_SUBTITLE = Styles(font_size="11px", opacity="0.72", word_break="break-word")
_QUOTE_OTHER = Styles(
    display="flex",
    flex_direction="column",
    gap="2px",
    max_width="100%",
    padding="7px 10px",
    border_radius="8px",
    background_color=stub.surface,
)
_QUOTE_ME = _QUOTE_OTHER.model_copy(update={"background_color": Color(rgba=(255, 255, 255, 0.16))})
_QUOTE_TITLE = Styles(font_size="12px", font_weight="600", opacity="0.8")
_QUOTE_BODY = Styles(
    font_size="12px",
    opacity="0.85",
    word_break="break-word",
    white_space="pre-wrap",
)
_LINK = Styles(
    display="flex",
    flex_direction="column",
    gap="2px",
    color=Color(name="inherit"),
    text_decoration="none",
)

_FILE_DOWNLOAD_BUTTON = Styles(
    display="inline-flex",
    align_items="center",
    justify_content="center",
    padding="3px 8px",
    border="none",
    border_radius="6px",
    background_color=Color(name="transparent"),
    color=Color(name="currentColor"),
    font_size="12px",
    cursor="pointer",
    opacity="0.85",
)

_REACTIONS_ROW = Styles(
    display="flex",
    flex_wrap="wrap",
    gap="4px",
    margin_top="6px",
)

_REACTION = Styles(
    display="inline-flex",
    align_items="center",
    gap="4px",
    padding="3px 8px 3px 6px",
    border_radius="12px",
    background_color=stub.surface_glass_bg,
    cursor="pointer",
    font_size="13px",
    line_height="1",
)

_REACTION_EMOJI = Styles(
    font_size="14px",
    line_height="1",
)

_REACTION_COUNT = Styles(
    font_size="11px",
    color=stub.text_secondary,
    line_height="1",
    margin_left="1px",
)


def build_message_content(
    message: Message,
    on_image_click: ImageClickHandler | None = None,
    on_file_download: FileDownloadHandler | None = None,
) -> DOMElement:
    """把消息元素渲染为 MessageBubble 的 content。

    Neony 只允许 element children，因此所有文本都先包进 Span。
    """
    children: list[DOMElement] = []
    elements = message.elements
    index = 0
    while index < len(elements):
        element = elements[index]
        if isinstance(element, _INLINE_ELEMENT_TYPES):
            inline: list[DOMElement] = []
            while index < len(elements) and isinstance(elements[index], _INLINE_ELEMENT_TYPES):
                inline.append(_build_element(elements[index], message.from_self, on_image_click, on_file_download))
                index += 1
            children.append(Span(styles=_INLINE_GROUP, container=inline))
        else:
            children.append(_build_element(element, message.from_self, on_image_click, on_file_download))
            index += 1

    # 添加表情回应显示
    if message.reactions:
        reactions_row = _build_reactions(message)
        if reactions_row is not None:
            children.append(reactions_row)

    return Div(styles=_CONTENT, container=children)


def _build_reactions(message: Message) -> DOMElement | None:
    """渲染消息的表情回应行（表情与计数分开显示，避免混淆）。"""
    if not message.reactions:
        return None
    reaction_els: list[DOMElement] = []
    for r in message.reactions:
        if r.count <= 0:
            continue
        emoji_span = Span(container=[r.emoji_id], styles=_REACTION_EMOJI)
        count_span = Span(container=[str(r.count)], styles=_REACTION_COUNT)
        reaction_els.append(Div(styles=_REACTION, container=[emoji_span, count_span]))
    if not reaction_els:
        return None
    return Div(styles=_REACTIONS_ROW, container=reaction_els)


def _build_element(
    element: MessageElement,
    from_self: bool,
    on_image_click: ImageClickHandler | None,
    on_file_download: FileDownloadHandler | None,
) -> DOMElement:
    if isinstance(element, TextElement):
        return Span(container=[element.text], styles=_TEXT)

    if isinstance(element, AtElement):
        return _at_span(element.text, from_self)
    if isinstance(element, AtAllElement):
        return _at_span(element.text, from_self)

    if isinstance(element, ImageElement):
        src = _image_url(element.url, element.cached_path)
        if src:
            loading = "eager" if src.startswith("data:") else "lazy"
            image = Img(src=src, alt=element.preview_text, loading=loading, styles=_sized_image_styles(element))
            if on_image_click is not None:
                _attach_image_click(
                    image,
                    ImagePreview(src=src, alt=element.preview_text, width=element.width, height=element.height),
                    on_image_click,
                )
            return image
        return _card("图片", _format_size(element.size))

    if isinstance(element, MarketFaceElement):
        if element.face_id:
            src = _image_url(element.url, element.cached_path)
            loading = "eager" if src.startswith("data:") else "lazy"
            return Img(
                src=src,
                alt=element.name or element.preview_text,
                loading=loading,
                styles=_sized_market_face_styles(element),
            )
        return _card("动画表情", element.name)

    if isinstance(element, EmojiElement):
        return _card("QQ 表情", f"ID {element.id}")

    if isinstance(element, AudioElement):
        src = _local_or_remote_url(element.url, element.cached_path)
        if src:
            return Audio(src=src, controls=True, preload="none", styles=_AUDIO)
        return _card("语音", _format_duration(element.time))

    if isinstance(element, VideoElement):
        src = _local_or_remote_url(element.url, element.cached_path)
        if src:
            return Video(src=src, controls=True, preload="metadata", styles=_sized_video_styles(element))
        return _card("视频", _format_duration(element.time))

    if isinstance(element, FileElement):
        parts: list[DOMElement] = []
        href = _local_or_remote_url(element.file_url or "", element.cached_path)
        if href:
            parts.append(
                Anchor(
                    href=href,
                    target="_blank",
                    rel="noopener noreferrer",
                    download=element.file_name,
                    styles=_LINK,
                    container=[
                        Span(container=[element.file_name], styles=_CARD_TITLE),
                        Span(container=[_format_size(element.file_size)], styles=_CARD_SUBTITLE),
                    ],
                )
            )
        if on_file_download is not None:
            button = Button("下载", variant="ghost").reset_styles(_FILE_DOWNLOAD_BUTTON)

            async def download(_event: DomEvent) -> None:
                await on_file_download(element)

            button.on_click(download)
            parts.append(button.build())
        if parts:
            return Div(styles=_CARD, container=parts)
        detail = element.file_name
        size_text = _format_size(element.file_size)
        if size_text:
            detail = f"{detail}（{size_text}）"
        return _card("文件", detail)

    if isinstance(element, PokeElement):
        return _card("戳一戳", f"ID {element.id}")

    if isinstance(element, QuoteElement):
        return _quote(element, from_self)

    if isinstance(element, ForwardElement):
        return _card("聊天记录", element.file_name or "合并转发消息")

    if isinstance(element, UnknownElement):
        return _card(element.display, element.original_kind)

    return _card("[未知消息]", type(element).__name__)


def _attach_image_click(image: Img, preview: ImagePreview, callback: ImageClickHandler) -> None:
    async def open_preview(_event: DomEvent) -> None:
        await callback(preview)

    image.on_click(open_preview)


def _local_or_remote_url(remote_url: str, cached_path: str) -> str:
    """本地文件存在时优先返回 file://，否则回退远程 URL。

    当前 WebView 环境对图片的 file:// 加载不可靠，因此图片使用
    ``_image_url`` 走 data: URL；本函数只服务音频、视频和文件。
    """
    if cached_path:
        path = Path(cached_path)
        if path.is_file():
            return file_url(path)
    return remote_url


def _image_url(remote_url: str, cached_path: str) -> str:
    """图片优先内嵌本地缓存 data URL，失败则回退远程 URL。"""
    if cached_path:
        path = Path(cached_path)
        if path.is_file():
            return _cached_image_data_url(str(path))
    return remote_url


@lru_cache(maxsize=64)
def _cached_image_data_url(path: str) -> str:
    return data_url(path, _sniff_image_mime(path))


def _sniff_image_mime(path: str) -> str:
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type and mime_type.startswith("image/"):
        return mime_type

    with open(path, "rb") as file:
        header = file.read(16)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return "image/gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _sized_image_styles(element: ImageElement) -> Styles:
    styles = _IMAGE
    if element.width <= 0:
        return styles
    return styles.model_copy(update={"width": f"{min(element.width, 360)}px"})


def _sized_market_face_styles(element: MarketFaceElement) -> Styles:
    styles = _IMAGE
    if element.width <= 0:
        return styles
    return styles.model_copy(update={"width": f"{min(element.width, 180)}px"})


def _sized_video_styles(element: VideoElement) -> Styles:
    styles = _VIDEO
    if element.width <= 0:
        return styles.model_copy(update={"width": "100%"})
    return styles.model_copy(update={"width": f"{min(element.width, 420)}px"})


def _at_span(text: str, from_self: bool) -> Span:
    return Span(
        container=[text],
        styles=_TEXT.model_copy(
            update={
                "font_weight": "600",
                "color": _AT_COLOR_ME if from_self else _AT_COLOR_OTHER,
            }
        ),
    )


def _quote(element: QuoteElement, from_self: bool) -> Div:
    styles = _QUOTE_ME if from_self else _QUOTE_OTHER
    sender = str(element.uin) if element.uin else "未知发送者"
    timestamp = _format_quote_timestamp(element.timestamp)
    title = f"{sender} · {timestamp}" if timestamp else sender
    return Div(
        styles=styles,
        container=[
            Span(container=[title], styles=_QUOTE_TITLE),
            Span(container=[element.msg or "原消息不可见"], styles=_QUOTE_BODY),
        ],
    )


def _format_quote_timestamp(timestamp: int) -> str:
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def _card(title: str, subtitle: str = "") -> Div:
    children: list[DOMElement] = [Span(container=[title], styles=_CARD_TITLE)]
    if subtitle:
        children.append(Span(container=[subtitle], styles=_CARD_SUBTITLE))
    return Div(styles=_CARD, container=children)


def _format_size(size: int) -> str:
    if size <= 0:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _format_duration(seconds: int) -> str:
    return f"{seconds} 秒" if seconds > 0 else ""
