"""设置对话框。"""

from __future__ import annotations

from neony.application.elements import Dialog, DialogAction

from flaza.config import LoginConfig
from flaza.ui.actions import UiActions
from flaza.ui.components.login_config_form import LoginConfigForm


class SettingsDialog:
    """包含登录配置表单的模态设置对话框。"""

    def __init__(self, actions: UiActions, initial: LoginConfig) -> None:
        self._actions = actions
        self.form = LoginConfigForm(initial)
        self.dialog = Dialog(
            title="设置",
            content=self.form.root,
            open=True,
            width="440px",
            actions=[
                DialogAction("保存", on_click=self._on_save, close_on_click=False),
                DialogAction("取消", variant="ghost"),
            ],
        )

    async def _on_save(self, _dialog: Dialog) -> None:
        try:
            self.form.set_error("")
            actions = self._actions
            actions.save_login_config(self.form.values())
        except Exception as exc:
            self.form.set_error(f"保存失败：{exc}")
