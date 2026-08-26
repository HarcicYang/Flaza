"""插件宿主加载、事件扩展与异常隔离测试。"""

import asyncio
import json
import sys

from flaza.config import AppConfig, PathsConfig
from flaza.plugins import PluginHost
from flaza.runtime import ApplicationRuntime


def _make_config(tmp_path, plugins_dir) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            plugins_dir=str(plugins_dir),
            plugin_state_path=str(tmp_path / "plugin_state.json"),
        )
    )


def _write_plugin(plugins_dir, plugin_id: str, code: str) -> None:
    plugin_dir = plugins_dir / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps({"id": plugin_id, "name": plugin_id, "entry": "main.py"}),
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text(code, encoding="utf-8")


def test_host_loads_plugin_and_custom_event(tmp_path) -> None:
    plugins_dir = tmp_path / "plugins"
    _write_plugin(
        plugins_dir,
        "demo",
        """
import asyncio

from flaza.core.events import FlazaEvent
from flaza.plugins import FlazaPlugin


class Ping(FlazaEvent):
    value: str


class Demo(FlazaPlugin):
    def __init__(self) -> None:
        self.seen: list[str] = []
        self.done = asyncio.Event()
        self.ctx = None
        self.unloaded = False

    async def on_load(self, ctx) -> None:
        self.ctx = ctx
        ctx.subscribe(Ping, self.on_ping)

    async def on_ping(self, event: Ping) -> None:
        self.seen.append(event.value)
        self.done.set()

    async def on_unload(self) -> None:
        self.unloaded = True


plugin = Demo()
""",
    )
    runtime = ApplicationRuntime(_make_config(tmp_path, plugins_dir))
    host = PluginHost(runtime)

    async def scenario() -> None:
        await host.start()
        module = sys.modules["flaza_plugin_demo.main"]
        plugin = module.plugin
        bus_task = asyncio.create_task(runtime.bus.run())
        plugin.ctx.publish(module.Ping(value="插件事件"))
        await asyncio.wait_for(plugin.done.wait(), timeout=1)
        assert plugin.seen == ["插件事件"]

        await host.stop()
        assert plugin.unloaded is True
        assert "flaza_plugin_demo.main" not in sys.modules
        bus_task.cancel()
        await asyncio.gather(bus_task, return_exceptions=True)

    asyncio.run(scenario())


def test_host_skips_broken_plugin_and_keeps_others(tmp_path) -> None:
    plugins_dir = tmp_path / "plugins"
    _write_plugin(
        plugins_dir,
        "bad",
        "raise RuntimeError('boom')\n",
    )
    _write_plugin(
        plugins_dir,
        "good",
        """
from flaza.plugins import FlazaPlugin


class Good(FlazaPlugin):
    pass


plugin = Good()
""",
    )
    runtime = ApplicationRuntime(_make_config(tmp_path, plugins_dir))
    host = PluginHost(runtime)

    async def scenario() -> None:
        await host.start()
        assert host.loaded == ("good",)
        await host.stop()

    asyncio.run(scenario())


def test_host_reload_reads_plugin_files_from_disk_each_time(tmp_path) -> None:
    plugins_dir = tmp_path / "plugins"
    _write_plugin(
        plugins_dir,
        "demo",
        """
from . import helper
from flaza.plugins import FlazaPlugin


class Demo(FlazaPlugin):
    pass


plugin = Demo()
value = helper.value
""",
    )
    plugin_dir = plugins_dir / "demo"
    (plugin_dir / "helper.py").write_text("value = 1\n", encoding="utf-8")

    runtime = ApplicationRuntime(_make_config(tmp_path, plugins_dir))
    host = PluginHost(runtime)

    async def scenario() -> None:
        await host.start()
        assert sys.modules["flaza_plugin_demo.main"].value == 1

        (plugin_dir / "helper.py").write_text("value = 2\n", encoding="utf-8")
        (plugin_dir / "main.py").write_text(
            """
from . import helper
from flaza.plugins import FlazaPlugin


class Demo(FlazaPlugin):
    pass


plugin = Demo()
value = helper.value + 10
""",
            encoding="utf-8",
        )
        await host.reload()

        assert sys.modules["flaza_plugin_demo.main"].value == 12
        await host.stop()

    asyncio.run(scenario())
