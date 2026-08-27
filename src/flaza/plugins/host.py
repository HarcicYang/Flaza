"""插件发现、动态加载、生命周期与任务托管。"""

from __future__ import annotations

import asyncio
import importlib
import importlib.machinery
import importlib.util
import logging
import re
import shutil
import sys
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, override

from flaza.plugins.api import FlazaPlugin
from flaza.plugins.context import PluginContext
from flaza.plugins.manifest import PluginCandidate, PluginDiscovery, PluginManifest, check_dependencies
from flaza.plugins.registry import PluginExtensionRegistry
from flaza.plugins.state import PluginState

if TYPE_CHECKING:
    from flaza.runtime import ApplicationRuntime

logger = logging.getLogger(__name__)


@dataclass
class _LoadedPlugin:
    manifest: PluginManifest
    module: ModuleType
    module_package: str
    plugin: FlazaPlugin
    context: PluginContext


@dataclass(frozen=True)
class PluginSnapshot:
    """插件管理界面使用的发现、启停与运行状态快照。"""

    path: Path
    manifest: PluginManifest
    enabled: bool
    loaded: bool


class PluginHost:
    """插件宿主：只做基础错误隔离与退出清理，不承诺防御恶意插件。"""

    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime
        paths = runtime.config.paths
        self._discovery = PluginDiscovery(paths.plugins_dir)
        self._state = PluginState(paths.plugin_state_path)
        self._plugins: dict[str, _LoadedPlugin] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def registry(self) -> PluginExtensionRegistry:
        return self._runtime.plugin_registry

    @property
    def loaded(self) -> tuple[str, ...]:
        return tuple(self._plugins)

    async def start(self) -> None:
        """发现、校验并启动启用的插件；依赖缺失只警告不阻止。"""
        if self._plugins:
            return
        self._state.load()
        candidates = self._discover_candidates()
        for candidate in candidates:
            manifest = candidate.manifest
            if not self._state.is_enabled(manifest.id):
                logger.info("插件已禁用，跳过: %s", manifest.id)
                continue
            self._check_dependencies(manifest)
            await self._load_plugin(candidate)

    async def load(self) -> None:
        """start 的别名，便于在运行时接入点中表达“加载”。"""
        await self.start()

    async def stop(self) -> None:
        """停止插件、清理订阅与托管任务，再移除动态导入路径。"""
        module_packages = [loaded.module_package for loaded in self._plugins.values()]
        for loaded in reversed(list(self._plugins.values())):
            plugin_id = loaded.manifest.id
            try:
                await loaded.plugin.on_unload()
            except Exception:
                logger.exception("插件 on_unload 执行失败: %s", plugin_id)
            for subscription in loaded.context.subscriptions:
                subscription.dispose()
            loaded.context.subscriptions.clear()
            self._runtime.plugin_registry.remove_plugin(plugin_id)
        self._plugins.clear()
        await self._cancel_tasks()
        for module_package in module_packages:
            self._cleanup_module(module_package)

    async def unload(self) -> None:
        """stop 的别名。"""
        await self.stop()

    def snapshot(self) -> tuple[PluginSnapshot, ...]:
        """返回发现结果与每个插件的启停、运行状态，供管理界面渲染。"""
        self._state.load()
        return tuple(
            PluginSnapshot(
                path=candidate.path,
                manifest=candidate.manifest,
                enabled=self._state.is_enabled(candidate.manifest.id),
                loaded=candidate.manifest.id in self._plugins,
            )
            for candidate in self._discover_candidates()
        )

    async def reload(self) -> None:
        """停止全部插件，再按运行时当前配置重新发现并加载。"""
        await self.stop()
        await self.start()

    async def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        """持久化启停状态并立即重载，让新状态生效。"""
        self._state.set_enabled(plugin_id, enabled)
        await self.reload()

    def spawn_task(self, coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """托管一个后台任务；插件停止时统一取消。"""
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ---- 内部 ----

    def _discover_candidates(self) -> list[PluginCandidate]:
        """按当前配置发现候选插件，目录变更后无需重启即可重载。"""
        self._discovery = PluginDiscovery(self._runtime.config.paths.plugins_dir)
        return self._discovery.discover()

    async def _load_plugin(self, candidate: PluginCandidate) -> None:
        manifest = candidate.manifest
        context: PluginContext | None = None
        module_package = ""
        try:
            entry_path = _resolve_entry(candidate.path, manifest.entry)
            _clear_bytecode_caches(candidate.path)
            module_package = _make_plugin_package(manifest.id, candidate.path)
            module_name = _module_name(module_package, entry_path, candidate.path)
            module = _import_entry_module(module_name, entry_path)
            plugin = getattr(module, "plugin", None)
            if not isinstance(plugin, FlazaPlugin):
                raise TypeError("插件入口没有导出 FlazaPlugin 实例（模块级 plugin）")
            context = PluginContext(manifest.id, self._runtime, self._runtime.bus, self._state, self)
            await plugin.on_load(context)
        except Exception:
            logger.exception("插件加载失败: %s", manifest.id)
            if context is not None:
                for subscription in context.subscriptions:
                    subscription.dispose()
                context.subscriptions.clear()
            self._runtime.plugin_registry.remove_plugin(manifest.id)
            self._cleanup_module(module_package)
            return

        self._plugins[manifest.id] = _LoadedPlugin(
            manifest=manifest,
            module=module,
            module_package=module_package,
            plugin=plugin,
            context=context,
        )
        logger.info("插件已加载: %s v%s", manifest.id, manifest.version)

    def _check_dependencies(self, manifest: PluginManifest) -> None:
        for issue in check_dependencies(manifest):
            logger.warning(
                "插件 %s 依赖未满足: %s（%s），插件自行处理",
                manifest.id,
                issue.requirement,
                issue.detail,
            )

    def _cleanup_module(self, module_package: str) -> None:
        _purge_module_tree(module_package)

    async def _cancel_tasks(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


def _resolve_entry(plugin_dir: Path, entry: str) -> Path:
    raw = Path(entry)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError(f"entry 必须是插件目录内的相对路径: {entry}")
    if raw.suffix == "":
        raw = raw.with_suffix(".py")
    resolved = plugin_dir / raw
    if not resolved.is_file():
        raise FileNotFoundError(f"入口文件不存在: {resolved}")
    return resolved


def _make_plugin_package(plugin_id: str, plugin_dir: Path) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9_]", "_", plugin_id)
    package_name = f"flaza_plugin_{safe_id}"
    _purge_module_tree(package_name)
    spec = importlib.machinery.ModuleSpec(package_name, None, is_package=True)
    spec.submodule_search_locations = [str(plugin_dir)]
    sys.modules[package_name] = importlib.util.module_from_spec(spec)
    return package_name


def _import_entry_module(module_name: str, entry_path: Path) -> ModuleType:
    """从入口文件直接构建模块，不依赖 sys.modules 里可能残留的旧模块。"""
    importlib.invalidate_caches()
    loader = _DiskSourceLoader(module_name, str(entry_path))
    spec = importlib.util.spec_from_file_location(module_name, entry_path, loader=loader)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载插件入口: {entry_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _DiskSourceLoader(importlib.machinery.SourceFileLoader):
    """始终重新编译插件源码，绕开可能过期的 .pyc 缓存。"""

    @override
    def get_code(self, fullname: str) -> Any:
        source = self.get_data(self.path)
        return compile(source, self.path, "exec", dont_inherit=True)


def _purge_module_tree(module_package: str) -> None:
    prefix = f"{module_package}."
    for name in list(sys.modules):
        if name == module_package or name.startswith(prefix):
            sys.modules.pop(name, None)


def _clear_bytecode_caches(plugin_dir: Path) -> None:
    """每次加载都清掉插件目录内的 .pyc 缓存，强制从源码重新编译。"""
    for path in plugin_dir.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def _module_name(module_package: str, entry_path: Path, plugin_dir: Path) -> str:
    relative = entry_path.relative_to(plugin_dir)
    parts = list(relative.parts)
    parts[-1] = entry_path.stem
    submodule = ".".join(parts)
    return f"{module_package}.{submodule}" if submodule else module_package
