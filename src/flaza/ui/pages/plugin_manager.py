"""插件管理页面。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from neony.application import icons
from neony.application.elements import Badge, Button, Heading, HStack, Input, Spacer, Switch, Text, VStack
from neony.application.theme import stub
from neony.dom import Animation, Div, DOMElement, DomEvent, Span, Styles

from flaza.plugins.host import PluginSnapshot
from flaza.ui.actions import UiActions

_PLUGIN_ROW = Styles(
    display="flex",
    flex_direction="column",
    gap="8px",
    padding="14px 16px",
    border_radius="8px",
    background_color=stub.surface,
    border="1px solid var(--color-border)",
    flex_shrink="0",
)

_PLUGIN_NAME = Styles(
    font_size="15px",
    font_weight="600",
    color=stub.text_primary,
    min_width="0",
    overflow="hidden",
    text_overflow="ellipsis",
    white_space="nowrap",
)


class PluginManagerPage:
    """插件目录与插件启停状态管理页。"""

    def __init__(
        self,
        actions: UiActions,
        render: Callable[[], Awaitable[None]],
        on_close: Callable[[], Awaitable[None]],
    ) -> None:
        self._actions = actions
        self._render = render
        self._on_close = on_close
        self._plugins_dir_input = Input(
            value=actions.current_config().paths.plugins_dir,
            placeholder="./plugins",
        )
        self._status = Text("", role="danger")
        self._list_container = Div(styles=Styles(display="flex", flex_direction="column", gap="10px"))

        back = Button("返回设置", variant="ghost", icon=icons.chevron_left)
        back.on_click(self._on_back)
        reload_button = Button("重新加载", variant="ghost", icon=icons.refresh)
        reload_button.on_click(self._on_reload)
        browse_button = Button("浏览", variant="ghost")
        browse_button.on_click(self._on_browse)
        apply_button = Button("应用并重载")
        apply_button.on_click(self._on_apply_dir)

        input_wrap = Div(
            styles=Styles(flex_grow="1", min_width="0"),
            container=[self._plugins_dir_input.build()],
        )
        directory_row = HStack(
            input_wrap,
            browse_button,
            apply_button,
            gap="8px",
            align="center",
            width="100%",
        )
        header = HStack(
            back,
            Heading("插件管理", level=1),
            Spacer(),
            reload_button,
            gap="12px",
            align="center",
            width="100%",
        )
        directory_section = VStack(
            Text("插件目录", size="14px", weight="600"),
            directory_row,
            self._status,
            gap="10px",
            align="stretch",
            width="100%",
        )
        list_section = VStack(
            Text("插件列表", size="14px", weight="600"),
            self._list_container,
            gap="10px",
            align="stretch",
            width="100%",
        )

        panel = VStack(
            header,
            directory_section,
            list_section,
            gap="22px",
            align="stretch",
            width="720px",
        ).build()
        panel.styles = panel.styles.model_copy(
            update={
                "margin": "0 auto",
                "max_width": "100%",
                "flex_shrink": "0",
                "padding_bottom": "32px",
            }
        )
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
        self._rebuild_list()

    # ---- 事件 ----

    async def _on_back(self, _event: DomEvent) -> None:
        await self._on_close()

    async def _on_browse(self, _event: DomEvent) -> None:
        folder = await self._actions.pick_plugins_dir()
        if folder:
            self._plugins_dir_input.value = folder

    async def _on_apply_dir(self, _event: DomEvent) -> None:
        try:
            await self._actions.save_plugins_dir(self._plugins_dir_input.value)
            self._status.text = ""
        except Exception as exc:
            self._status.text = f"保存插件目录失败：{exc}"
        self._rebuild_list()
        await self._render()

    async def _on_reload(self, _event: DomEvent) -> None:
        try:
            await self._actions.reload_plugins()
            self._status.text = ""
        except Exception as exc:
            self._status.text = f"重新加载插件失败：{exc}"
        self._rebuild_list()
        await self._render()

    def _make_toggle_handler(self, plugin_id: str, switch: Switch):
        async def handler(_event: DomEvent) -> None:
            try:
                await self._actions.set_plugin_enabled(plugin_id, switch.checked)
                self._status.text = ""
            except Exception as exc:
                self._status.text = f"切换插件失败：{exc}"
            self._rebuild_list()
            await self._render()

        return handler

    # ---- 列表 ----

    def _rebuild_list(self) -> None:
        self._list_container.container.clear()
        try:
            snapshots = self._actions.list_plugins()
        except Exception as exc:
            self._status.text = f"读取插件列表失败：{exc}"
            return
        if not snapshots:
            self._list_container.container.append(Text("插件目录下暂未发现插件", role="secondary").build())
            return
        for snapshot in snapshots:
            self._list_container.container.append(self._build_plugin_row(snapshot))

    def _build_plugin_row(self, snapshot: PluginSnapshot) -> DOMElement:
        manifest = snapshot.manifest
        name = manifest.name.strip() or manifest.id
        name_el = Span(container=[name], styles=_PLUGIN_NAME)

        enabled_badge = Badge(
            "已启用" if snapshot.enabled else "已禁用",
            variant="success" if snapshot.enabled else "neutral",
        )
        loaded_badge = Badge(
            "已加载" if snapshot.loaded else "未加载",
            variant="accent" if snapshot.loaded else "neutral",
        )
        badges = HStack(enabled_badge, loaded_badge, gap="6px", align="center")
        if snapshot.enabled and not snapshot.loaded:
            badges = HStack(badges, Badge("加载失败", variant="danger"), gap="6px", align="center")

        switch = Switch(label="启用", checked=snapshot.enabled)
        switch.on_change(self._make_toggle_handler(manifest.id, switch))
        title_row = HStack(
            name_el,
            badges,
            Spacer(),
            switch,
            gap="10px",
            align="center",
            width="100%",
        )
        description = Text(manifest.description or "无描述", role="secondary", size="13px")
        version = f"v{manifest.version}" if manifest.version else ""
        meta = Text(f"{manifest.id}{' ' + version if version else ''} · {snapshot.path}", role="secondary", size="12px")
        return Div(styles=_PLUGIN_ROW, container=[title_row.build(), description.build(), meta.build()])
