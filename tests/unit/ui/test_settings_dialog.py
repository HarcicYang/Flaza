"""设置对话框测试。"""

import asyncio

import pytest

import flaza.ui.actions as actions_module
from flaza.config import AppConfig
from flaza.runtime import ApplicationRuntime
from flaza.ui.components.settings_dialog import SettingsDialog


def test_settings_dialog_contains_login_form_and_theme() -> None:
    config = AppConfig()
    runtime = ApplicationRuntime(config)
    dialog = SettingsDialog(runtime.actions, config.login, config.window)

    assert dialog.form is not None
    assert dialog._theme_group.value == "dark"
    assert dialog.dialog.title == "设置"


def test_save_theme_persists_config_and_applies_without_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig()
    runtime = ApplicationRuntime(config)
    saved: list[AppConfig] = []

    def fake_save(config: AppConfig) -> None:
        saved.append(config)

    monkeypatch.setattr(actions_module, "save_config", fake_save)

    async def scenario() -> None:
        await runtime.actions.save_theme("light")
        assert runtime.config.window.theme == "light"
        assert runtime.actions.current_config().window.theme == "light"
        assert saved[-1].window.theme == "light"

        reopened = SettingsDialog(
            runtime.actions, runtime.actions.current_config().login, runtime.actions.current_config().window
        )
        assert reopened._theme_group.value == "light"

    asyncio.run(scenario())
