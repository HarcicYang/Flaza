"""设置对话框。"""

from __future__ import annotations

from typing import cast

from neony.application.elements import CascadingDropdown, Dialog, DialogAction, MenuBranch, ScrollArea, Text, VStack

from flaza.config import LoginConfig, ThemeName, WindowSettings
from flaza.ui.actions import UiActions
from flaza.ui.components.login_config_form import LoginConfigForm


class SettingsDialog:
    """包含登录配置和当前实际支持的应用设置。"""

    def __init__(self, actions: UiActions, initial_login: LoginConfig, initial_window: WindowSettings) -> None:
        self._actions = actions
        self._initial_login = initial_login
        self._initial_window = initial_window
        self.form = LoginConfigForm(initial_login)
        self._theme_dropdown = CascadingDropdown(
            "选择主题",
            items=(
                MenuBranch("Nightglow", (("nightglow-dark", "深色"), ("nightglow-light", "浅色"))),
                MenuBranch("Planet Plaza", (("planet-plaza-dark", "深色"), ("planet-plaza-light", "浅色"))),
                MenuBranch("Ember Zone", (("ember-zone-dark", "深色"), ("ember-zone-light", "浅色"))),
                MenuBranch("Cyberangel", (("cyberangel-dark", "深色"), ("cyberangel-light", "浅色"))),
            ),
            width="160px",
        )
        self._theme_dropdown.value = initial_window.theme
        self._error = Text("", role="danger")

        form_content = VStack(
            Text("登录配置", size="14px", weight="600"),
            self.form.root,
            Text("应用设置", size="14px", weight="600"),
            Text("主题"),
            self._theme_dropdown,
            self._error,
            gap="12px",
            align="stretch",
        ).build()
        content = ScrollArea(form_content).build()
        content.styles = content.styles.model_copy(update={"height": "min(560px, 60vh)"})

        self.dialog = Dialog(
            title="设置",
            content=content,
            open=True,
            width="440px",
            actions=[
                DialogAction("保存", on_click=self._on_save, close_on_click=False),
                DialogAction("取消", variant="ghost"),
            ],
        )

    async def _on_save(self, dialog: Dialog) -> None:
        try:
            self.form.set_error("")
            self._error.text = ""

            theme = cast(ThemeName, self._theme_dropdown.value)
            login = self.form.values()

            if theme != self._initial_window.theme:
                await self._actions.save_theme(theme)
            if login != self._initial_login:
                # 登录配置生效需要重启；save_theme 已把新主题写入 runtime.config。
                self._actions.save_login_config(login)
                return

            dialog.open = False
        except Exception as exc:
            self.form.set_error(f"保存失败：{exc}")
            self._error.text = f"保存失败：{exc}"
