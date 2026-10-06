"""设置页面测试。"""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from neony.dom import Animation, KeyFrame
from neony.dom.base import DOMElement

import flaza.ui.actions as actions_module
from flaza.config import AppConfig, LoginConfig
from flaza.runtime import ApplicationRuntime
from flaza.ui.components.login_config_form import LoginConfigForm
from flaza.ui.pages.settings import SettingsPage


def _settings_page(
    runtime: ApplicationRuntime,
    on_close: Callable[[], Awaitable[None]] | None = None,
) -> SettingsPage:
    async def default_close() -> None:
        return None

    async def default_open_plugins() -> None:
        return None

    return SettingsPage(
        runtime.actions,
        runtime.config.login,
        runtime.config.window,
        runtime.config.paths,
        runtime.render,
        on_close or default_close,
        default_open_plugins,
    )


def test_settings_page_contains_login_form_and_theme() -> None:
    runtime = ApplicationRuntime(AppConfig())
    page = _settings_page(runtime)

    assert page.form is not None
    assert page._theme_dropdown.value == "nightglow-dark"
    assert page._chat_open_position_dropdown.value == "bottom"
    assert page._chat_open_position_dropdown._label_by_value == {
        "last": "上次位置",
        "bottom": "自动回到底部",
    }


def test_login_config_form_roundtrips_network_switches() -> None:
    form = LoginConfigForm(LoginConfig(uin=123, use_ipv6=False, use_optimum=False))

    values = form.values()

    assert values.use_ipv6 is False
    assert values.use_optimum is False
    defaults = LoginConfigForm(LoginConfig(uin=123)).values()
    assert defaults.use_ipv6 is True
    assert defaults.use_optimum is True


def test_settings_page_contains_plugin_directory_and_manager() -> None:
    runtime = ApplicationRuntime(AppConfig())
    page = _settings_page(runtime)

    assert page._plugins_dir_input.value == "./plugins"
    assert _contains_text(page.root, "插件管理")


def _contains_text(element: DOMElement, text: str) -> bool:
    for child in element.container:
        if child == text:
            return True
        if isinstance(child, DOMElement) and _contains_text(child, text):
            return True
    return False


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


def test_save_chat_open_position_persists_config(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = ApplicationRuntime(AppConfig())
    saved: list[AppConfig] = []

    def fake_save(config: AppConfig) -> None:
        saved.append(config)

    monkeypatch.setattr(actions_module, "save_config", fake_save)

    async def scenario() -> None:
        await runtime.actions.save_chat_open_position("last")
        assert runtime.config.window.chat_open_position == "last"
        assert runtime.actions.current_config().window.chat_open_position == "last"
        assert saved[-1].window.chat_open_position == "last"

        reopened = _settings_page(runtime)
        assert reopened._chat_open_position_dropdown.value == "last"

    asyncio.run(scenario())


def test_settings_page_mounts_with_open_animation() -> None:
    runtime = ApplicationRuntime(AppConfig())
    page = _settings_page(runtime)

    animation = page.root.styles.animation
    assert isinstance(animation, Animation)
    assert animation.name == "flaza-page-in"
    assert animation.duration == "0.22s"


def test_register_page_keyframes_registers_ui_motion() -> None:
    from flaza.app import register_page_keyframes

    class _FakeApp:
        def __init__(self) -> None:
            self.names: list[str] = []

        def register_keyframe(self, kf: KeyFrame) -> "_FakeApp":
            self.names.append(kf.name)
            return self

    fake = _FakeApp()
    register_page_keyframes(fake)  # type: ignore[arg-type]
    assert fake.names == [
        "flaza-page-in",
        "flaza-page-out",
        "flaza-msg-in",
        "flaza-msg-out",
        "flaza-notice-in",
        "flaza-badge-pop",
        "flaza-badge-pop-alt",
        "flaza-viewer-in",
        "flaza-viewer-out",
        "flaza-image-in",
    ]
