"""独立设置页面。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import cast

from neony.application import icons
from neony.application.elements import Button, CascadingDropdown, Heading, HStack, Input, MenuBranch, Text, VStack
from neony.dom import Animation, Div, DomEvent, Styles

from flaza.config import ChatOpenPosition, LoginConfig, PathsConfig, ThemeName, WindowSettings
from flaza.core.models import OnlineClient, UserProfile
from flaza.ui.actions import UiActions
from flaza.ui.components.login_config_form import LoginConfigForm

logger = logging.getLogger(__name__)


class SettingsPage:
    """可滚动的应用设置页，不使用 Dialog overlay。"""

    def __init__(
        self,
        actions: UiActions,
        initial_login: LoginConfig,
        initial_window: WindowSettings,
        initial_paths: PathsConfig,
        render: Callable[[], Awaitable[None]],
        on_close: Callable[[], Awaitable[None]],
        on_open_plugins: Callable[[], Awaitable[None]],
        initial_profile: UserProfile | None = None,
        initial_other_clients: Sequence[OnlineClient] = (),
    ) -> None:
        self._actions = actions
        self._initial_login = initial_login
        self._initial_window = initial_window
        self._initial_paths = initial_paths
        self._render = render
        self._on_close = on_close
        self._open_plugins = on_open_plugins
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
        self._chat_open_position_dropdown = CascadingDropdown(
            "打开会话位置",
            items=(
                ("last", "上次位置"),
                ("bottom", "自动回到底部"),
            ),
            width="180px",
        )
        self._chat_open_position_dropdown.value = initial_window.chat_open_position
        self._plugins_dir_input = Input(value=initial_paths.plugins_dir, placeholder="./plugins")
        self._error = Text("", role="danger")
        self._nickname_input = Input(
            value=initial_profile.nickname if initial_profile is not None else "",
            placeholder="昵称",
        )
        self._bio_input = Input(
            value=initial_profile.bio if initial_profile is not None else "",
            placeholder="个性签名",
        )
        self._profile_status = Text("", role="success", size="12px")
        self._other_clients_text = Text(
            "、".join(client.display_name for client in initial_other_clients) or "无其它在线端",
            role="secondary",
            size="12px",
        )

        save = Button("保存")
        save.on_click(self._on_save)
        cancel = Button("返回", variant="ghost")
        cancel.on_click(self._on_cancel)
        browse_plugins = Button("浏览", variant="ghost")
        browse_plugins.on_click(self._on_browse_plugins)
        manage_plugins = Button("插件管理", variant="ghost", icon=icons.settings)
        manage_plugins.on_click(self._on_open_plugins)
        save_profile = Button("保存资料", variant="ghost")
        save_profile.on_click(self._on_save_profile)
        change_avatar = Button("更换头像", variant="ghost")
        change_avatar.on_click(self._on_change_avatar)

        plugins_input_wrap = Div(
            styles=Styles(flex_grow="1", min_width="0"),
            container=[self._plugins_dir_input.build()],
        )
        plugins_dir_row = Div(
            styles=Styles(display="flex", align_items="center", gap="8px"),
            container=[plugins_input_wrap, browse_plugins.build()],
        )
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
            Text("打开会话位置"),
            self._chat_open_position_dropdown,
            gap="12px",
            align="stretch",
        ).build()
        plugin_section = VStack(
            Text("插件", size="14px", weight="600"),
            Text("插件目录"),
            plugins_dir_row,
            manage_plugins,
            gap="12px",
            align="stretch",
        ).build()
        profile_section = VStack(
            Text("个人资料", size="14px", weight="600"),
            Text("昵称"),
            self._nickname_input,
            Text("个性签名"),
            self._bio_input,
            HStack(save_profile, change_avatar, gap="8px").build(),
            self._profile_status,
            gap="12px",
            align="stretch",
        ).build()
        device_section = VStack(
            Text("其它在线端", size="14px", weight="600"),
            self._other_clients_text,
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
            profile_section,
            app_section,
            plugin_section,
            device_section,
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
            position = cast(ChatOpenPosition, self._chat_open_position_dropdown.value)
            login = self.form.values()
            plugins_dir = self._plugins_dir_input.value.strip()
            if theme != self._initial_window.theme:
                await self._actions.save_theme(theme)
            if position != self._initial_window.chat_open_position:
                await self._actions.save_chat_open_position(position)
            if plugins_dir != self._initial_paths.plugins_dir:
                await self._actions.save_plugins_dir(plugins_dir)
            if login != self._initial_login:
                self._actions.save_login_config(login)
                return
            await self._on_close()
        except Exception as exc:
            message = f"保存失败：{exc}"
            self.form.set_error(message)
            self._error.text = message
            await self._render()

    async def _on_save_profile(self, _event: DomEvent) -> None:
        try:
            self._profile_status.text = ""
            await self._actions.update_self_profile(self._nickname_input.value, self._bio_input.value)
            self._profile_status.text = "资料已保存"
            await self._render()
        except Exception as exc:
            logger.exception("保存个人资料失败")
            self._profile_status.text = ""
            self._error.text = f"保存资料失败：{exc}"
            await self._render()

    async def _on_change_avatar(self, _event: DomEvent) -> None:
        try:
            path = await self._actions.pick_avatar_file()
            if not path:
                return
            await self._actions.update_self_avatar(path)
            self._profile_status.text = "头像已更新"
            await self._render()
        except Exception:
            logger.exception("更新头像失败")
            self._error.text = "更新头像失败"
            await self._render()

    async def _on_cancel(self, _event: DomEvent) -> None:
        await self._on_close()

    async def _on_browse_plugins(self, _event: DomEvent) -> None:
        folder = await self._actions.pick_plugins_dir()
        if folder:
            self._plugins_dir_input.value = folder

    async def _on_open_plugins(self, _event: DomEvent) -> None:
        await self._open_plugins()
