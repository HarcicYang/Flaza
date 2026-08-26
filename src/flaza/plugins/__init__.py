"""Flaza 插件系统基础层。"""

from flaza.plugins.api import FlazaPlugin
from flaza.plugins.context import PluginContext
from flaza.plugins.host import PluginHost, PluginSnapshot
from flaza.plugins.manifest import PluginDiscovery, PluginManifest
from flaza.plugins.registry import PluginExtensionRegistry, Registration
from flaza.plugins.state import PluginState

__all__ = [
    "FlazaPlugin",
    "PluginContext",
    "PluginDiscovery",
    "PluginExtensionRegistry",
    "PluginHost",
    "PluginManifest",
    "PluginSnapshot",
    "PluginState",
    "Registration",
]
