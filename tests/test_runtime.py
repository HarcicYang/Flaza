"""应用组装冒烟测试。"""

from flaza.app import build_application
from flaza.config import AppConfig
from flaza.ui.pages.home import HomePage


def test_build_application_without_login_config_shows_setup() -> None:
    _app, runtime = build_application(AppConfig())
    assert runtime.shell._screen == "setup"


def test_build_application_with_login_config_shows_login() -> None:
    config = AppConfig(login={"uin": 123, "signer_url": "https://sign.example.com"})
    _app, runtime = build_application(config)
    assert runtime.shell._screen == "login"


def test_login_page_opens_settings_and_returns() -> None:
    import asyncio

    config = AppConfig(login={"uin": 123, "signer_url": "https://sign.example.com"})
    _app, runtime = build_application(config)

    async def render() -> None:
        return None

    runtime.shell._render = render

    async def scenario() -> None:
        await runtime.shell._open_settings()
        assert runtime.shell._screen == "settings"
        await runtime.shell._close_settings()
        assert runtime.shell._screen == "login"

    asyncio.run(scenario())


def test_home_page_can_be_constructed() -> None:
    config = AppConfig(login={"uin": 123, "signer_url": "https://sign.example.com"})
    _app, runtime = build_application(config)
    home = HomePage(runtime.state, runtime.actions, runtime.bus, config, runtime.render)
    assert len(home.root.container) == 5
