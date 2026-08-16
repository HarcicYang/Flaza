"""ShellView：统一自定义标题栏与页面内容切换。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from neony.application.elements import Button, Icon, Text, TitleBar
from neony.dom import Computed, Div, DOMElement, DomEvent, Styles

from flaza.config import AppConfig
from flaza.core.events import EventBus, LoginPhaseChanged
from flaza.core.models import LoginPhase
from flaza.ui.actions import UiActions
from flaza.ui.avatars import friend_avatar_url
from flaza.ui.pages.home import HomePage
from flaza.ui.pages.login import LoginPage
from flaza.ui.pages.setup import SetupPage
from flaza.ui.state import UiStateStore

_TOOLBAR = Styles(display="flex", align_items="center", gap="6px", flex_shrink="0")


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
        self._home: HomePage | None = None

        titlebar = TitleBar(config.window.title, icon=Icon.image(friend_avatar_url(0)))
        titlebar_root = titlebar.build()

        account = Text("", role="secondary")
        account.bind_text(
            state.self_info,
            fmt=lambda info: f"{info.nickname or str(info.uin)}（{info.uin}）" if info else "未登录",
        )
        connection = Text("", role="secondary")
        connection.bind_text(state.connection_state, fmt=lambda value: f"连接：{value.value}")

        spacer = Div(styles=Styles(flex_grow="1"))
        self._toolbar = Div(styles=_TOOLBAR)

        left = titlebar_root.container[0]
        if not isinstance(left, DOMElement):
            raise RuntimeError("TitleBar 根结构不符合预期")
        icon_el = left.container[0]
        if isinstance(icon_el, DOMElement):
            icon_el.styles = icon_el.styles.model_copy(
                update={
                    "width": "22px",
                    "height": "22px",
                    "border_radius": "50%",
                    "overflow": "hidden",
                    "background_size": "cover",
                }
            )

            def current_uin() -> int:
                info = state.self_info()
                return info.uin if info is not None else 0

            self_uin = Computed(current_uin)
            icon_el.bind_style(self_uin, "background_image", fmt=lambda uin: f"url({friend_avatar_url(int(uin))})")
        left.container.extend([spacer, account.build(), connection.build(), self._toolbar])

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
            self._mount(LoginPage(state, actions, config, render).root)

        bus.subscribe(LoginPhaseChanged, self._on_login_phase)

    async def _on_login_phase(self, event: LoginPhaseChanged) -> None:
        if event.phase is LoginPhase.ONLINE and self._screen != "main":
            self._screen = "main"
            home = HomePage(self._state, self._actions, self._bus, self._config, self._render)
            self._home = home
            self._mount(home.root)
            self._install_main_toolbar(home)
            await self._render()

    def _mount(self, element: DOMElement) -> None:
        self._content.container.clear()
        self._content.container.append(element)

    def _install_main_toolbar(self, home: HomePage) -> None:
        async def open_new_chat(_event: DomEvent) -> None:
            await home.open_new_chat()

        async def open_settings(_event: DomEvent) -> None:
            await home.open_settings()

        self._toolbar.container.clear()
        new_chat = Button("新会话", variant="ghost")
        new_chat.on_click(open_new_chat)
        settings = Button("设置", variant="ghost")
        settings.on_click(open_settings)
        self._toolbar.container.extend([new_chat.build(), settings.build()])
