"""消息输入与发送组件。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from neony.application.elements import Button, Input, Text
from neony.dom import Div, DomEvent, Signal, Styles

from flaza.ui.actions import UiActions


class Composer:
    """单行输入框 + 发送按钮。"""

    def __init__(self, actions: UiActions, render: Callable[[], Awaitable[None]]) -> None:
        self._actions = actions
        self._render = render
        self._input = Input(placeholder="输入消息…")
        self._draft = Signal("")
        self._input.bind_value(self._draft)
        self._send_button = Button("发送")
        self._error = Text("", role="danger")

        input_wrap = Div(styles=Styles(flex_grow="1", display="flex"), container=[self._input.build()])
        self._send_button.on_click(self._on_send)
        self._input.on_keydown(self._on_keydown)

        self.root = Div(
            styles=Styles(display="flex", flex_direction="column", gap="6px", padding="12px 16px"),
            container=[
                Div(
                    styles=Styles(display="flex", align_items="center", gap="8px"),
                    container=[input_wrap, self._send_button.build()],
                ),
                self._error.build(),
            ],
        )

    async def _send(self) -> None:
        text = self._draft().strip()
        if not text:
            return
        self._send_button.disabled = True
        try:
            self._error.text = ""
            await self._actions.send_message(text)
            self._draft.set("")
        except Exception as exc:
            self._error.text = f"发送失败：{exc}"
        finally:
            self._send_button.disabled = False
        await self._render()

    async def _on_send(self, _event: DomEvent) -> None:
        await self._send()

    async def _on_keydown(self, event: DomEvent) -> None:
        if event.value == "Enter":
            await self._send()
