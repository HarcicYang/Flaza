"""消息元素 DOM 渲染测试。"""

import asyncio
from pathlib import Path

from neony.dom import Anchor, Audio, Div, DOMElement, DomEvent, Img, Span, Video

from flaza.core.models import (
    AtElement,
    AudioElement,
    FileElement,
    FriendChat,
    GroupChat,
    ImageElement,
    MarketFaceElement,
    Message,
    MessageReaction,
    PokeElement,
    QuoteElement,
    TextElement,
    UnknownElement,
    VideoElement,
)
from flaza.ui.components.image_viewer import ImagePreview
from flaza.ui.components.message_content import build_message_content


def _message(*elements: object) -> Message:
    return Message(
        chat=FriendChat(uid="u_1", uin=10001),
        sender_uin=10001,
        sender_uid="u_1",
        seq=1,
        timestamp=100,
        elements=list(elements),  # type: ignore[arg-type]
    )


def _walk(element: DOMElement) -> list[DOMElement]:
    found: list[DOMElement] = []
    for child in element.container:
        if isinstance(child, DOMElement):
            found.append(child)
            found.extend(_walk(child))
    return found


def test_content_children_are_all_elements() -> None:
    root = build_message_content(
        _message(TextElement(text="你好\n第二行"), ImageElement(url="https://example.com/pic.png"), PokeElement(id=1))
    )

    assert isinstance(root, Div)
    assert root.container
    assert all(isinstance(child, DOMElement) for child in root.container)
    assert all(isinstance(child, DOMElement) for child in _walk(root))


def test_text_and_at_preserve_newlines() -> None:
    root = build_message_content(_message(TextElement(text="第一行\n第二行"), AtElement(text="@小明", uin=10001)))

    spans = [element for element in _walk(root) if isinstance(element, Span)]
    text_spans = [span for span in spans if span.container and span.container[0] == "第一行\n第二行"]
    assert text_spans
    assert text_spans[0].styles.white_space == "pre-wrap"
    assert any(span.styles.font_weight == "600" for span in spans)


def test_text_and_at_share_one_inline_group() -> None:
    root = build_message_content(
        _message(TextElement(text="你好 "), AtElement(text="@小明", uin=10001), TextElement(text=" 看这里"))
    )

    assert len(root.container) == 1
    group = root.container[0]
    assert isinstance(group, Span)
    assert len(group.container) == 3
    assert all(isinstance(child, DOMElement) for child in group.container)


def test_media_splits_inline_text_groups() -> None:
    root = build_message_content(
        _message(
            TextElement(text="看图"),
            ImageElement(url="https://example.com/pic.png"),
            TextElement(text="图后文本"),
        )
    )

    assert len(root.container) == 3
    assert isinstance(root.container[0], Span)
    assert isinstance(root.container[1], Img)
    assert isinstance(root.container[2], Span)


def test_image_audio_video_use_native_elements_when_url_present() -> None:
    root = build_message_content(
        _message(
            ImageElement(url="https://example.com/pic.png", width=640, height=480),
            AudioElement(url="https://example.com/voice.amr", time=3),
            VideoElement(url="https://example.com/clip.mp4", time=8),
        )
    )

    elements = _walk(root)
    assert sum(isinstance(element, Img) for element in elements) == 1
    assert sum(isinstance(element, Audio) for element in elements) == 1
    assert sum(isinstance(element, Video) for element in elements) == 1


def test_missing_media_url_renders_placeholder_cards() -> None:
    root = build_message_content(
        _message(AudioElement(time=3), VideoElement(time=8), ImageElement(width=640, height=480))
    )

    descendants = _walk(root)
    cards = [element for element in descendants if isinstance(element, Div) and element.styles.border]
    assert len(cards) == 3
    assert sum(isinstance(element, Audio) for element in descendants) == 0
    assert sum(isinstance(element, Video) for element in descendants) == 0


def test_file_with_url_renders_download_anchor() -> None:
    root = build_message_content(
        _message(
            FileElement(
                file_name="资料.zip",
                file_size=1024,
                file_url="https://example.com/资料.zip",
            )
        )
    )

    anchors = [element for element in _walk(root) if isinstance(element, Anchor)]
    assert len(anchors) == 1
    assert anchors[0].href == "https://example.com/资料.zip"
    assert anchors[0].download == "资料.zip"
    assert anchors[0].target == "_blank"


def test_cached_image_uses_data_url_and_keeps_size_in_mixed_content(tmp_path: Path) -> None:
    local_file = tmp_path / "pic.png"
    local_file.write_bytes(b"\x89PNG\r\n\x1a\nlocal-bytes")
    root = build_message_content(
        _message(
            TextElement(text="图"),
            ImageElement(
                url="https://example.com/pic.png",
                width=640,
                height=480,
                cached_path=str(local_file),
            ),
        )
    )

    images = [element for element in _walk(root) if isinstance(element, Img)]
    assert len(images) == 1
    assert images[0].src is not None
    assert images[0].src.startswith("data:image/png;base64,")
    assert images[0].loading == "eager"
    assert images[0].styles.width == "360px"
    assert images[0].styles.flex_shrink == "0"
    assert images[0].styles.align_self == "flex-start"


def test_missing_cached_file_falls_back_to_remote_url(tmp_path: Path) -> None:
    root = build_message_content(
        _message(
            ImageElement(
                url="https://example.com/pic.png",
                cached_path=str(tmp_path / "missing.png"),
            )
        )
    )

    images = [element for element in _walk(root) if isinstance(element, Img)]
    assert len(images) == 1
    assert images[0].src == "https://example.com/pic.png"


def test_audio_and_video_are_not_squeezed_in_mixed_content() -> None:
    root = build_message_content(
        _message(
            TextElement(text="听一下"),
            AudioElement(url="https://example.com/voice.amr", time=3),
            TextElement(text="再看一下"),
            VideoElement(url="https://example.com/clip.mp4", width=1280, height=720, time=8),
        )
    )

    audios = [element for element in _walk(root) if isinstance(element, Audio)]
    videos = [element for element in _walk(root) if isinstance(element, Video)]
    assert len(audios) == 1
    assert len(videos) == 1
    assert audios[0].styles.width == "100%"
    assert audios[0].styles.flex_shrink == "0"
    assert videos[0].styles.width == "420px"
    assert videos[0].styles.flex_shrink == "0"


def _quote_blocks(root: DOMElement) -> list[Div]:
    return [
        element
        for element in _walk(root)
        if isinstance(element, Div) and element.styles.background_color is not None and element.styles.border is None
    ]


def test_quote_uses_background_depth_instead_of_border() -> None:
    other_root = build_message_content(
        _message(QuoteElement(seq=1, uin=10001, timestamp=1, msg="原文")).model_copy(update={"from_self": False})
    )
    self_root = build_message_content(
        _message(QuoteElement(seq=1, uin=10001, timestamp=1, msg="原文")).model_copy(update={"from_self": True})
    )

    other_blocks = _quote_blocks(other_root)
    self_blocks = _quote_blocks(self_root)
    assert len(other_blocks) == 1
    assert len(self_blocks) == 1
    assert other_blocks[0].styles.border is None
    assert self_blocks[0].styles.border is None
    assert other_blocks[0].styles.background_color is not None
    assert self_blocks[0].styles.background_color is not None
    assert other_blocks[0].styles.background_color != self_blocks[0].styles.background_color
    title = other_blocks[0].container[0]
    assert isinstance(title, Span)
    title_text = title.container[0]
    assert isinstance(title_text, str)
    assert title_text.startswith("10001 · 1970-01-01")


def test_image_click_callback_receives_preview() -> None:
    previews: list[ImagePreview] = []

    async def on_image_click(preview: ImagePreview) -> None:
        previews.append(preview)

    root = build_message_content(
        _message(ImageElement(url="https://example.com/pic.png", width=640, height=480)),
        on_image_click=on_image_click,
    )

    images = [element for element in _walk(root) if isinstance(element, Img)]
    assert len(images) == 1
    handlers = images[0]._handlers.get("click", [])
    assert handlers

    async def run_handlers() -> None:
        for handler in handlers:
            await handler(DomEvent(key=images[0].key, type="click", source="user"))

    import asyncio

    asyncio.run(run_handlers())
    assert len(previews) == 1
    assert previews[0].src == "https://example.com/pic.png"
    assert previews[0].width == 640
    assert previews[0].height == 480


def test_market_face_does_not_open_image_preview() -> None:
    previews: list[ImagePreview] = []

    async def on_image_click(preview: ImagePreview) -> None:
        previews.append(preview)

    root = build_message_content(
        _message(MarketFaceElement(name="表情", face_id=b"abc", tab_id=1, width=100, height=100)),
        on_image_click=on_image_click,
    )

    images = [element for element in _walk(root) if isinstance(element, Img)]
    assert len(images) == 1
    assert not images[0]._handlers.get("click")
    assert previews == []


def test_unknown_element_renders_display_text() -> None:
    root = build_message_content(_message(UnknownElement(original_kind="json", display="[卡片消息]")))

    spans = [element for element in _walk(root) if isinstance(element, Span)]
    assert any(span.container and span.container[0] == "[卡片消息]" for span in spans)


def test_reaction_pill_shows_self_reacted_highlight() -> None:
    """自己回应的 emoji 使用高亮背景，未回应的使用普通背景。"""
    calls: list[str] = []

    async def on_click(emoji_id: str) -> None:
        calls.append(emoji_id)

    message = _message(TextElement(text="hi")).model_copy(
        update={
            "chat": GroupChat(group_id=20001),
            "reactions": [
                MessageReaction(emoji_id="😊", count=2, users=["u_self", "u_other"]),
                MessageReaction(emoji_id="👍", count=1, users=["u_other"]),
            ],
        }
    )
    root = build_message_content(message, on_reaction_click=on_click, self_uid="u_self")

    pills = [el for el in _walk(root) if isinstance(el, Div) and el.styles.cursor == "pointer"]
    assert len(pills) == 2
    assert pills[0].styles.background_color is not None
    self_pill = pills[0]
    other_pill = pills[1]
    # self_uid 在 😊 的 users 中，所以第一个 pill 用高亮背景
    assert self_pill.styles.background_color != other_pill.styles.background_color

    # 点击第二个 pill（👍），回调应收到 emoji_id
    handlers = other_pill._handlers.get("click", [])
    assert handlers

    async def run() -> None:
        for handler in handlers:
            await handler(DomEvent(key=other_pill.key, type="click"))

    asyncio.run(run())
    assert calls == ["👍"]


def test_local_media_prefers_neony_protocol(tmp_path: Path) -> None:
    """本地缓存存在时走 neony://local/（file:// 会被 WebKit 拦截）。"""
    from flaza.ui.components.message_content import _local_or_remote_url

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    url = _local_or_remote_url("https://expired.example/v.mp4", str(video))
    assert url.startswith("neony://local/")
    assert "clip.mp4" in url

    missing = _local_or_remote_url("https://example.com/v.mp4", str(tmp_path / "gone.mp4"))
    assert missing == "https://example.com/v.mp4"

    no_cache = _local_or_remote_url("https://example.com/v.mp4", "")
    assert no_cache == "https://example.com/v.mp4"
