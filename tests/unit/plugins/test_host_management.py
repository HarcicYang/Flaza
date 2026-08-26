"""插件宿主启停、快照与目录热切换测试。"""

import asyncio
import json

import pytest

import flaza.ui.actions as actions_module
from flaza.config import AppConfig, PathsConfig
from flaza.runtime import ApplicationRuntime


def _make_config(tmp_path, plugins_dir: str) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            plugins_dir=plugins_dir,
            plugin_state_path=str(tmp_path / "plugin_state.json"),
        )
    )


def _write_plugin(plugins_dir, plugin_id: str) -> None:
    plugin_dir = plugins_dir / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps({"id": plugin_id, "name": plugin_id, "entry": "main.py"}),
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


def test_host_set_plugin_enabled_unloads_and_reloads(tmp_path) -> None:
    plugins_dir = tmp_path / "plugins"
    _write_plugin(plugins_dir, "demo")
    runtime = ApplicationRuntime(_make_config(tmp_path, str(plugins_dir)))
    host = runtime.plugins

    async def scenario() -> None:
        await host.start()
        assert host.loaded == ("demo",)
        assert host.snapshot()[0].enabled is True
        assert host.snapshot()[0].loaded is True

        await host.set_plugin_enabled("demo", False)
        assert host.loaded == ()
        snapshot = host.snapshot()
        assert snapshot[0].enabled is False
        assert snapshot[0].loaded is False

        await host.set_plugin_enabled("demo", True)
        assert host.loaded == ("demo",)
        snapshot = host.snapshot()
        assert snapshot[0].enabled is True
        assert snapshot[0].loaded is True
        await host.stop()

    asyncio.run(scenario())


def test_save_plugins_dir_switches_directory_without_restart(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugins_a = tmp_path / "plugins_a"
    plugins_b = tmp_path / "plugins_b"
    _write_plugin(plugins_a, "alpha")
    _write_plugin(plugins_b, "beta")

    saved: list[AppConfig] = []

    def fake_save(config: AppConfig) -> None:
        saved.append(config)

    monkeypatch.setattr(actions_module, "save_config", fake_save)
    runtime = ApplicationRuntime(_make_config(tmp_path, str(plugins_a)))
    host = runtime.plugins

    async def scenario() -> None:
        await host.start()
        assert host.loaded == ("alpha",)
        await runtime.actions.save_plugins_dir(str(plugins_b))
        assert runtime.config.paths.plugins_dir == str(plugins_b)
        assert host.loaded == ("beta",)
        assert host.snapshot()[0].path == plugins_b / "beta"
        assert saved[-1].paths.plugins_dir == str(plugins_b)
        await host.stop()

    asyncio.run(scenario())
