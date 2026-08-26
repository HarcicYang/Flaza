"""custom-theme 示例插件行为测试。"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from flaza.core.events import EventBus
from flaza.plugins import PluginContext
from flaza.plugins.registry import PluginExtensionRegistry
from flaza.plugins.state import PluginState

_EXAMPLE_PLUGIN = Path(__file__).resolve().parents[3] / "examples" / "plugins" / "custom-theme"


def test_custom_theme_example_applies_and_removes_variables(tmp_path: Path) -> None:
    async def scenario() -> None:
        variables = {
            "--color-bg": "#101418",
            "--color-text-primary": "#e8edf2",
            "--color-accent": "#d98e4a",
        }
        state = PluginState(str(tmp_path / "state.json"))
        state.set_setting("custom-theme", "variables", variables)

        scripts: list[str] = []

        async def eval_js(script: str) -> None:
            scripts.append(script)

        runtime = SimpleNamespace(eval_js=eval_js)
        registry = PluginExtensionRegistry()
        host = SimpleNamespace(registry=registry)
        context = PluginContext("custom-theme", runtime, EventBus(), state, host)

        plugin = _load_plugin()
        await plugin.on_load(context)

        assert len(scripts) == 1
        for key, value in variables.items():
            assert f"setProperty({json.dumps(key)}, {json.dumps(value)})" in scripts[0]

        await plugin.on_unload()

        assert len(scripts) == 2
        for key in variables:
            assert f"removeProperty({json.dumps(key)})" in scripts[1]

    asyncio.run(scenario())


def _load_plugin():
    module_name = "example_custom_theme_under_test"
    spec = importlib.util.spec_from_file_location(module_name, _EXAMPLE_PLUGIN / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.plugin
