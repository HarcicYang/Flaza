"""设置对话框。"""

from __future__ import annotations

from typing import Literal, cast

from neony.application.elements import Dialog, DialogAction, Radio, RadioGroup, Text, VStack

from flaza.config import LoginConfig, WindowSettings
from flaza.ui.actions import UiActions
from flaza.ui.components.login_config_form import LoginConfigForm


class SettingsDialog:
    """包含登录配置和当前实际支持的应用设置。"""

    def __init__(self, actions: UiActions, initial_login: LoginConfig, initial_window: WindowSettings) -> None:
        self._actions = actions
        self._initial_login = initial_login
        self._initial_window = initial_window
        self.form = LoginConfigForm(initial_login)
        self._theme_group = RadioGroup(
            Radio("深色", value="dark"),
            Radio("浅色", value="light"),
            Radio("深蓝", value="deep_blue"),
            value=initial_window.theme,
            orientation="horizontal",
        )
        self._error = Text("", role="danger")

        content = VStack(
            Text("登录配置", size="14px", weight="600"),
            self.form.root,
            Text("应用设置", size="14px", weight="600"),
            Text("主题"),
            self._theme_group,
            self._error,
            gap="12px",
            align="stretch",
        ).build()

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

            theme = cast(Literal["dark", "light", "deep_blue"], self._theme_group.value)
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
