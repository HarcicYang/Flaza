"""首次配置页。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from neony.application.elements import Button, Heading, Text, VStack
from neony.dom import Div, DomEvent, Styles

from flaza.config import AppConfig
from flaza.ui.actions import UiActions
from flaza.ui.components.login_config_form import LoginConfigForm


class SetupPage:
    """登录配置不完整时显示的引导页。"""

    def __init__(self, actions: UiActions, config: AppConfig, render: Callable[[], Awaitable[None]]) -> None:
        self._actions = actions
        self._render = render
        self.form = LoginConfigForm(config.login)
        save_button = Button("保存并重启")
        save_button.on_click(self._on_save)

        panel = VStack(
            Heading("欢迎使用 Flaza", level=1),
            Text("首次使用需要先配置登录信息。保存后应用会自动重启。", role="secondary"),
            self.form.root,
            save_button.build(),
            gap="16px",
            width="440px",
        ).build()

        self.root = Div(
            styles=Styles(
                flex_grow="1",
                width="100%",
                display="flex",
                align_items="center",
                justify_content="center",
                padding="24px",
                overflow_y="auto",
            ),
            container=[panel],
        )

    async def _on_save(self, _event: DomEvent) -> None:
        try:
            self.form.set_error("")
            self._actions.save_login_config(self.form.values())
        except Exception as exc:
            self.form.set_error(f"保存失败：{exc}")
            await self._render()
