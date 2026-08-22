"""独立设置页面。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from neony.application.elements import Button, CascadingDropdown, Heading, MenuBranch, Text, VStack
from neony.dom import Animation, Div, DomEvent, Styles

from flaza.config import LoginConfig, ThemeName, WindowSettings
from flaza.ui.actions import UiActions
from flaza.ui.components.login_config_form import LoginConfigForm


class SettingsPage:
    """可滚动的应用设置页，不使用 Dialog overlay。"""

    def __init__(
        self,
        actions: UiActions,
        initial_login: LoginConfig,
        initial_window: WindowSettings,
        render: Callable[[], Awaitable[None]],
        on_close: Callable[[], Awaitable[None]],
    ) -> None:
        self._actions = actions
        self._initial_login = initial_login
        self._initial_window = initial_window
        self._render = render
        self._on_close = on_close
        self.form = LoginConfigForm(initial_login)
        self._theme_dropdown = CascadingDropdown(
            "选择主题",
            items=(
                MenuBranch("Nightglow", (("nightglow-dark", "深色"), ("nightglow-light", "浅色"))),
                MenuBranch("Planet Plaza", (("planet-plaza-dark", "深色"), ("planet-plaza-light", "浅色"))),
                MenuBranch("Ember Zone", (("ember-zone-dark", "深色"), ("ember-zone-light", "浅色"))),
                MenuBranch("Cyberangel", (("cyberangel-dark", "深色"), ("cyberangel-light", "浅色"))),
            ),
            width="180px",
        )
        self._theme_dropdown.value = initial_window.theme
        self._error = Text("", role="danger")

        save = Button("保存")
        save.on_click(self._on_save)
        cancel = Button("返回", variant="ghost")
        cancel.on_click(self._on_cancel)
        login_section = VStack(
            Text("登录配置", size="14px", weight="600"),
            self.form.root,
            gap="16px",
            align="stretch",
        ).build()
        app_section = VStack(
            Text("应用设置", size="14px", weight="600"),
            Text("主题"),
            self._theme_dropdown,
            gap="12px",
            align="stretch",
        ).build()
        actions_row = Div(
            styles=Styles(display="flex", justify_content="flex-end", gap="8px"),
            container=[cancel.build(), save.build()],
        )
        panel = VStack(
            Heading("设置", level=1),
            login_section,
            app_section,
            self._error,
            actions_row,
            gap="24px",
            align="stretch",
            width="440px",
        ).build()
        panel.styles = panel.styles.model_copy(update={"flex_shrink": "0", "padding_bottom": "24px"})
        self.root = Div(
            styles=Styles(
                flex_grow="1",
                min_height="0",
                width="100%",
                display="block",
                padding="24px",
                overflow_y="auto",
                animation=Animation(name="flaza-page-in", duration="0.22s", timing="ease-out"),
            ),
            container=[panel],
        )
        panel.styles = panel.styles.model_copy(update={"margin": "0 auto", "max_width": "100%"})

    async def _on_save(self, _event: DomEvent) -> None:
        try:
            self.form.set_error("")
            self._error.text = ""
            theme = cast(ThemeName, self._theme_dropdown.value)
            login = self.form.values()
            if theme != self._initial_window.theme:
                await self._actions.save_theme(theme)
            if login != self._initial_login:
                self._actions.save_login_config(login)
                return
            await self._on_close()
        except Exception as exc:
            message = f"保存失败：{exc}"
            self.form.set_error(message)
            self._error.text = message
            await self._render()

    async def _on_cancel(self, _event: DomEvent) -> None:
        await self._on_close()
