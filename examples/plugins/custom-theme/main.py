"""示例插件：自定义主题。

插件在加载时通过 ``ctx.runtime.eval_js`` 在 ``:root`` 上写入自己的 CSS
变量，渲染器会立即按新配色刷新；卸载时移除这些行内变量，恢复内置主题。
"""

from __future__ import annotations

import json

from flaza.plugins import FlazaPlugin, PluginContext

DEFAULT_VARIABLES = {
    "--color-bg": "#f7f1e5",
    "--color-surface": "#fffaf0",
    "--color-surface-raised": "#ffffff",
    "--color-text-primary": "#3f3a32",
    "--color-text-secondary": "#7d7264",
    "--color-accent": "#b45f3d",
    "--color-accent-dim": "#8d4a31",
    "--color-danger": "#c4524a",
    "--color-success": "#5d8a68",
    "--color-border": "rgba(120, 96, 66, 0.18)",
    "--color-shadow": "0 24px 70px rgba(76, 57, 35, 0.24)",
}


class CustomTheme(FlazaPlugin):
    def __init__(self) -> None:
        self.ctx: PluginContext | None = None
        self._keys: tuple[str, ...] = ()

    async def on_load(self, context: PluginContext) -> None:
        self.ctx = context
        variables = context.get_setting("variables", DEFAULT_VARIABLES)
        self._keys = tuple(variables)
        await context.runtime.eval_js(_set_script(variables))

    async def on_unload(self) -> None:
        context = self.ctx
        if context is None:
            return
        await context.runtime.eval_js(_remove_script(self._keys))


def _set_script(variables: dict[str, str]) -> str:
    calls = "".join(
        f"document.documentElement.style.setProperty({json.dumps(key)}, {json.dumps(value)});"
        for key, value in variables.items()
    )
    return calls


def _remove_script(keys: tuple[str, ...]) -> str:
    return "".join(
        f"document.documentElement.style.removeProperty({json.dumps(key)});"
        for key in keys
    )


plugin = CustomTheme()
