"""示例插件：切换到 Flaza 内置主题。"""

from __future__ import annotations

from flaza.plugins import FlazaPlugin, PluginContext


class CustomTheme(FlazaPlugin):
    def __init__(self) -> None:
        self.ctx: PluginContext | None = None

    async def on_load(self, context: PluginContext) -> None:
        self.ctx = context
        await context.apply_theme("planet-plaza-dark")


plugin = CustomTheme()
