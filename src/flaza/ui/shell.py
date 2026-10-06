"""ShellView：统一自定义标题栏与页面内容切换。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from neony.application import icons
from neony.application.elements import Button, Icon, Text, TitleBar
from neony.application.theme import stub
from neony.dom import Animation, Color, Computed, Div, DOMElement, DomEvent, Styles

from flaza.config import AppConfig
from flaza.core.events import EventBus, LoginPhaseChanged
from flaza.core.models import LoginPhase, UserProfile
from flaza.ui.actions import UiActions
from flaza.ui.avatars import friend_avatar_url
from flaza.ui.pages.home import HomePage
from flaza.ui.pages.login import LoginPage
from flaza.ui.pages.plugin_manager import PluginManagerPage
from flaza.ui.pages.settings import SettingsPage
from flaza.ui.pages.setup import SetupPage
from flaza.ui.state import UiStateStore

logger = logging.getLogger(__name__)

_TOOLBAR = Styles(
    display="flex",
    align_items="center",
    gap="6px",
    flex_shrink="0",
    margin_left="14px",
)

_STATE_DOT = Styles(
    width="8px",
    height="8px",
    border_radius="50%",
    flex_shrink="0",
    background_color=Color(hex="#8e8e93"),
)

_STATE_DOT_COLORS = {
    "online": Color(hex="#30d158"),
    "connecting": Color(hex="#ffd60a"),
    "reconnecting": Color(hex="#ffd60a"),
    "offline": Color(hex="#ff453a"),
    "kicked": Color(hex="#ff453a"),
}

_TITLE_ICON = Styles(
    border_radius="50%",
    overflow="hidden",
    background_size="cover",
)

_ICON_BUTTON = Styles(
    display="flex",
    align_items="center",
    justify_content="center",
    width="32px",
    height="32px",
    padding="0",
    border="none",
    border_radius="8px",
    background_color=Color(name="transparent"),
    color=stub.text_primary,
    font_size="16px",
    cursor="pointer",
)


def _icon_button(icon: Icon, title: str) -> DOMElement:
    """构造带 title / aria-label 的紧凑图标按钮。"""
    button = Button("", variant="ghost", icon=icon)
    button.reset_styles(_ICON_BUTTON)
    element = button.build()
    element.args["title"] = title
    element.args["aria-label"] = title
    return element


class ShellView:
    """持有统一标题栏和页面内容根节点。"""

    def __init__(
        self,
        state: UiStateStore,
        actions: UiActions,
        bus: EventBus,
        config: AppConfig,
        render: Callable[[], Awaitable[None]],
    ) -> None:
        self._state = state
        self._actions = actions
        self._bus = bus
        self._config = config
        self._render = render
        self._screen = "setup" if not config.login_configured else "login"
        self._settings_return_screen = self._screen
        self._home: HomePage | None = None

        uin = Text("", role="secondary")
        uin.bind_text(state.self_info, fmt=lambda info: str(info.uin) if info is not None and info.uin else "")
        connection = Div(styles=_STATE_DOT)
        connection.bind_style(
            state.connection_state,
            "background_color",
            fmt=lambda value: _STATE_DOT_COLORS.get(value.value, Color(hex="#8e8e93")),
        )
        connection.bind_attr(
            state.connection_state,
            "title",
            fmt=lambda value: f"连接：{value.value}",
        )
        connection.bind_attr(
            state.connection_state,
            "aria-label",
            fmt=lambda value: f"连接：{value.value}",
        )
        self._toolbar = Div(styles=_TOOLBAR)

        avatar_icon = Icon.image(friend_avatar_url(0))
        avatar = avatar_icon.render("22px")
        avatar.styles = avatar.styles.model_copy(
            update={key: getattr(_TITLE_ICON, key) for key in _TITLE_ICON.model_fields_set}
        )
        uin_el = uin.build()
        spacer = Div(styles=Styles(flex_grow="1"))

        def current_title() -> str:
            info = state.self_info()
            return (info.nickname or "Flaza") if info is not None else config.window.title

        titlebar = TitleBar(
            Computed(current_title),
            leading=[avatar],
        )
        titlebar_root = titlebar.build()
        # UIN、状态点和主工具栏保持标题在左侧；右侧只留给系统窗口按钮。
        titlebar.leading_slot.container.extend([uin_el, spacer, connection, self._toolbar])

        def current_uin() -> int:
            info = state.self_info()
            return info.uin if info is not None else 0

        avatar.bind_style(
            Computed(current_uin),
            "background_image",
            fmt=lambda uid: f"url({friend_avatar_url(int(uid))})",
        )

        self._content = Div(
            styles=Styles(display="flex", flex_direction="column", flex_grow="1", min_height="0", overflow="hidden")
        )
        self.root = Div(
            styles=Styles(
                display="flex",
                flex_direction="column",
                width="100%",
                flex_grow="1",
                min_height="0",
                overflow="hidden",
            ),
            container=[titlebar_root, self._content],
        )

        if self._screen == "setup":
            self._mount(SetupPage(actions, config, render).root)
        else:
            self._mount(LoginPage(state, actions, config, render, self._open_settings).root)

        bus.subscribe(LoginPhaseChanged, self._on_login_phase)

    async def _on_login_phase(self, event: LoginPhaseChanged) -> None:
        if event.phase is LoginPhase.ONLINE and self._screen != "main":
            self._screen = "main"
            home = HomePage(
                self._state,
                self._actions,
                self._bus,
                self._config,
                self._render,
                plugin_registry=self._actions.plugin_registry,
            )
            self._home = home
            self._mount(home.root)
            self._install_main_toolbar(home)
            await self._render()

    def _mount(self, element: DOMElement) -> None:
        self._content.container.clear()
        self._content.container.append(element)

    async def _open_settings(self) -> None:
        config = self._actions.current_config()
        profile = await self._load_self_profile()
        self._settings_return_screen = self._screen
        self._toolbar.container.clear()
        self._screen = "settings"
        self._mount(
            SettingsPage(
                self._actions,
                config.login,
                config.window,
                config.paths,
                self._render,
                self._close_settings,
                self._open_plugin_manager,
                initial_profile=profile,
                initial_other_clients=self._state.other_clients(),
            ).root
        )
        await self._render()

    async def _open_plugin_manager(self) -> None:
        self._toolbar.container.clear()
        self._screen = "plugin_manager"
        self._mount(PluginManagerPage(self._actions, self._render, self._close_plugin_manager).root)
        await self._render()

    async def _close_plugin_manager(self) -> None:
        self._screen = "settings"
        config = self._actions.current_config()
        profile = await self._load_self_profile()
        self._mount(
            SettingsPage(
                self._actions,
                config.login,
                config.window,
                config.paths,
                self._render,
                self._close_settings,
                self._open_plugin_manager,
                initial_profile=profile,
                initial_other_clients=self._state.other_clients(),
            ).root
        )
        await self._render()

    async def _load_self_profile(self) -> UserProfile | None:
        """打开设置前拉取一次个人资料；离线时回退为空。"""
        info = self._state.self_info()
        if info is None:
            return None
        try:
            return await self._actions.fetch_user_profile(info.uid, info.uin)
        except Exception:
            logger.debug("获取个人资料失败", exc_info=True)
            return None

    async def _close_settings(self) -> None:
        # 先播退场动画，播完再切回原页面。
        if self._screen == "settings" and self._content.container:
            current = self._content.container[0]
            if isinstance(current, DOMElement):
                current.styles = current.styles.model_copy(
                    update={"animation": Animation(name="flaza-page-out", duration="0.16s", timing="ease-in")}
                )
                await self._render()
                await asyncio.sleep(0.16)
        if getattr(self, "_settings_return_screen", "main") == "login":
            self._screen = "login"
            self._mount(LoginPage(self._state, self._actions, self._config, self._render, self._open_settings).root)
        elif self._home is not None:
            self._screen = "main"
            self._mount(self._home.root)
            self._install_main_toolbar(self._home)
        await self._render()

    def _install_main_toolbar(self, home: HomePage) -> None:
        async def open_new_chat(_event: DomEvent) -> None:
            await home.open_new_chat()

        async def open_settings(_event: DomEvent) -> None:
            await self._open_settings()

        self._toolbar.container.clear()
        new_chat = _icon_button(icons.chat, "新会话")
        new_chat.on_click(open_new_chat)
        settings = _icon_button(icons.settings, "设置")
        settings.on_click(open_settings)
        self._toolbar.container.extend([new_chat, settings])
