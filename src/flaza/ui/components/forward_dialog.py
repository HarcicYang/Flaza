"""合并转发展开对话框。"""

from __future__ import annotations

from datetime import datetime

from neony.application.elements import Dialog, DialogAction, HStack, Spacer, Text, VStack
from neony.application.theme import stub
from neony.dom import Div, Styles

from flaza.core.models import Message, TextElement

_ROW = Styles(
    display="flex",
    flex_direction="column",
    gap="4px",
    padding="10px 12px",
    border="1px solid var(--color-border)",
    border_radius="8px",
    background_color=stub.surface_raised,
)


class ForwardDialog:
    """展示合并转发卡片里的消息记录。"""

    def __init__(self, messages: list[Message]) -> None:
        self.dialog = Dialog(
            title="聊天记录",
            content=self._build_content(messages),
            open=True,
            width="520px",
            actions=[DialogAction("关闭", variant="ghost")],
        )

    def _build_content(self, messages: list[Message]):
        rows = [self._build_row(message) for message in messages]
        if not rows:
            rows.append(Div(styles=_ROW, container=[Text("没有可展示的内容", role="secondary", size="13px").build()]))
        content = VStack(*rows, gap="8px", align="stretch").build()
        content.styles = content.styles.model_copy(update={"max_height": "520px", "overflow_y": "auto"})
        return content

    def _build_row(self, message: Message) -> Div:
        header = HStack(
            Text(message.sender_name or str(message.sender_uin), size="12px", weight="600").build(),
            Spacer().build(),
            Text(_format_time(message.timestamp), role="secondary", size="11px").build(),
            gap="8px",
            align="center",
        ).build()
        body = "\n".join(_element_text(element) for element in message.elements)
        return Div(
            styles=_ROW,
            container=[header, Text(body or "[空消息]", size="13px").build()],
        )


def _element_text(element: object) -> str:
    if isinstance(element, TextElement):
        return element.text
    return getattr(element, "preview_text", "[消息]")


def _format_time(timestamp: int) -> str:
    if not timestamp:
        return ""
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""
