"""插件管理页面测试。"""

import asyncio
import json
from pathlib import Path

from flaza.config import AppConfig, PathsConfig
from flaza.runtime import ApplicationRuntime
from flaza.ui.pages.plugin_manager import PluginManagerPage


def _write_plugin(plugins_dir: Path, plugin_id: str) -> None:
    plugin_dir = plugins_dir / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "name": "示例插件",
                "description": "测试插件",
                "entry": "main.py",
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text(
        """
from flaza.plugins import FlazaPlugin


class Demo(FlazaPlugin):
    pass


plugin = Demo()
""",
        encoding="utf-8",
    )


def test_plugin_manager_page_lists_plugins_and_directory(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    _write_plugin(plugins_dir, "demo")
    config = AppConfig(
        paths=PathsConfig(
            plugins_dir=str(plugins_dir),
            plugin_state_path=str(tmp_path / "plugin_state.json"),
        )
    )
    runtime = ApplicationRuntime(config)
    host = runtime.plugins
    closed = False

    async def close() -> None:
        nonlocal closed
        closed = True

    async def scenario() -> None:
        await host.start()
        page = PluginManagerPage(runtime.actions, runtime.render, close)
        assert page._plugins_dir_input.value == str(plugins_dir)
        assert len(page._list_container.container) == 1
        await page._on_back(None)  # type: ignore[arg-type]
        assert closed is True
        await host.stop()

    asyncio.run(scenario())


def test_plugin_manager_page_shows_empty_state(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    config = AppConfig(
        paths=PathsConfig(
            plugins_dir=str(plugins_dir),
            plugin_state_path=str(tmp_path / "plugin_state.json"),
        )
    )
    runtime = ApplicationRuntime(config)
    page = PluginManagerPage(runtime.actions, runtime.render, lambda: _noop())
    assert len(page._list_container.container) == 1


async def _noop() -> None:
    return None
