"""设置页面测试。"""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from neony.dom import Animation, KeyFrame

import flaza.ui.actions as actions_module
from flaza.config import AppConfig
from flaza.runtime import ApplicationRuntime
from flaza.ui.pages.settings import SettingsPage


def _settings_page(
    runtime: ApplicationRuntime,
    on_close: Callable[[], Awaitable[None]] | None = None,
) -> SettingsPage:
    async def default_close() -> None:
        return None

    return SettingsPage(
        runtime.actions,
        runtime.config.login,
        runtime.config.window,
        runtime.render,
        on_close or default_close,
    )


def test_settings_page_contains_login_form_and_theme() -> None:
    runtime = ApplicationRuntime(AppConfig())
    page = _settings_page(runtime)

    assert page.form is not None
    assert page._theme_dropdown.value == "nightglow-dark"


def test_save_theme_persists_config_and_applies_without_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig()
    runtime = ApplicationRuntime(config)
    saved: list[AppConfig] = []

    def fake_save(config: AppConfig) -> None:
        saved.append(config)

    monkeypatch.setattr(actions_module, "save_config", fake_save)

    async def scenario() -> None:
        await runtime.actions.save_theme("nightglow-light")
        assert runtime.config.window.theme == "nightglow-light"
        assert runtime.actions.current_config().window.theme == "nightglow-light"
        assert saved[-1].window.theme == "nightglow-light"

        reopened = _settings_page(runtime)
        assert reopened._theme_dropdown.value == "nightglow-light"

    asyncio.run(scenario())


def test_save_theme_returns_to_previous_page(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = ApplicationRuntime(AppConfig())

    def noop_save(_config: AppConfig) -> None:
        return None

    monkeypatch.setattr(actions_module, "save_config", noop_save)
    closed = False

    async def close() -> None:
        nonlocal closed
        closed = True

    page = _settings_page(runtime, close)

    async def scenario() -> None:
        page._theme_dropdown.value = "planet-plaza-light"
        await page._on_save(None)  # type: ignore[arg-type]
        assert closed is True

    asyncio.run(scenario())


def test_settings_page_mounts_with_open_animation() -> None:
    runtime = ApplicationRuntime(AppConfig())
    page = _settings_page(runtime)

    animation = page.root.styles.animation
    assert isinstance(animation, Animation)
    assert animation.name == "flaza-page-in"
    assert animation.duration == "0.22s"


def test_register_page_keyframes_registers_in_and_out() -> None:
    from flaza.app import register_page_keyframes

    class _FakeApp:
        def __init__(self) -> None:
            self.names: list[str] = []

        def register_keyframe(self, kf: KeyFrame) -> "_FakeApp":
            self.names.append(kf.name)
            return self

    fake = _FakeApp()
    register_page_keyframes(fake)  # type: ignore[arg-type]
    assert fake.names == ["flaza-page-in", "flaza-page-out"]
