"""custom-theme 示例插件行为测试。"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from flaza.core.events import EventBus
from flaza.plugins import PluginContext
from flaza.plugins.host import PluginHost
from flaza.plugins.registry import PluginExtensionRegistry
from flaza.plugins.state import PluginState
from flaza.runtime import ApplicationRuntime

_EXAMPLE_PLUGIN = Path(__file__).resolve().parents[3] / "examples" / "plugins" / "custom-theme"


def test_custom_theme_example_applies_builtin_theme(tmp_path: Path) -> None:
    async def scenario() -> None:
        state = PluginState(str(tmp_path / "state.json"))
        calls: list[str] = []

        async def set_theme(theme_name: str) -> None:
            calls.append(theme_name)

        runtime = cast(ApplicationRuntime, SimpleNamespace(set_theme=set_theme))
        registry = PluginExtensionRegistry()
        host = cast(PluginHost, SimpleNamespace(registry=registry))
        context = PluginContext("custom-theme", runtime, EventBus(), state, host)

        plugin = _load_plugin()
        await plugin.on_load(context)

        assert calls == ["planet-plaza-dark"]

    asyncio.run(scenario())


def _load_plugin():
    module_name = "example_custom_theme_under_test"
    spec = importlib.util.spec_from_file_location(module_name, _EXAMPLE_PLUGIN / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.plugin
