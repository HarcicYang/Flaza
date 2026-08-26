"""插件作者使用的基类与模块级约定。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flaza.plugins.context import PluginContext


class FlazaPlugin:
    """插件入口应导出模块级 ``plugin`` 实例。"""

    async def on_load(self, context: PluginContext) -> None:
        """插件启动；此时存储、EventBus 与插件状态均已就绪。"""

    async def on_unload(self) -> None:
        """插件停止；清理订阅与任务由插件宿主兜底。"""
