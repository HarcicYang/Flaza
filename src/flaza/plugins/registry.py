"""插件扩展注册表：过滤器、操作钩子与消息段扩展。"""

from __future__ import annotations

import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from flaza.core.models import ChatTarget, MessageElement, PluginElement

logger = logging.getLogger(__name__)

OutgoingMessageFilter = Callable[
    [ChatTarget, Sequence[MessageElement]],
    tuple[ChatTarget, Sequence[MessageElement]] | Awaitable[tuple[ChatTarget, Sequence[MessageElement]]] | None,
]
OutgoingFileFilter = Callable[
    [ChatTarget, str, str | None],
    tuple[ChatTarget, str, str | None] | Awaitable[tuple[ChatTarget, str, str | None]] | None,
]
RecallHook = Callable[[ChatTarget, int], bool | Awaitable[bool]]
ElementRenderer = Callable[[PluginElement], Any]
ElementSender = Callable[
    [ChatTarget, PluginElement],
    tuple[Any, MessageElement] | Awaitable[tuple[Any, MessageElement]],
]


@dataclass(frozen=True, slots=True)
class _OrderedEntry:
    plugin_id: str
    order: int
    handler: Callable[..., Awaitable[object]]


@dataclass(frozen=True, slots=True)
class _ElementEntry:
    plugin_id: str
    renderer: ElementRenderer | None
    sender: ElementSender | None


class Registration:
    """插件扩展注册句柄，dispose 后不再生效。"""

    def __init__(self, dispose: Callable[[], None]) -> None:
        self._dispose = dispose
        self._disposed = False

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._dispose()


class PluginExtensionRegistry:
    """集中持有按插件 id 登记的扩展点。

    过滤器或钩子里的异常只记录日志并跳过，避免一个插件的错误阻塞整条
    消息路径；消息段发送器异常会转化为一般 RuntimeError 向上抛出。
    """

    def __init__(self) -> None:
        self._message_filters: list[_OrderedEntry] = []
        self._file_filters: list[_OrderedEntry] = []
        self._recall_hooks: list[_OrderedEntry] = []
        self._elements: dict[tuple[str, str], _ElementEntry] = {}
        self._order = 0

    # ---- 过滤器与动作钩子 ----

    def register_outgoing_message_filter(
        self,
        plugin_id: str,
        handler: OutgoingMessageFilter,
    ) -> Registration:
        """注册出站消息过滤器；返回 None 表示中止发送。"""
        entry = _OrderedEntry(plugin_id, self._next_order(), handler)
        self._message_filters.append(entry)
        return Registration(lambda: _remove_entry(self._message_filters, entry))

    def register_outgoing_file_filter(
        self,
        plugin_id: str,
        handler: OutgoingFileFilter,
    ) -> Registration:
        """注册出站文件过滤器；返回 None 表示中止发送。"""
        entry = _OrderedEntry(plugin_id, self._next_order(), handler)
        self._file_filters.append(entry)
        return Registration(lambda: _remove_entry(self._file_filters, entry))

    def register_before_recall_hook(self, plugin_id: str, handler: RecallHook) -> Registration:
        """注册用户主动撤回的前置钩子；返回 False 表示中止撤回。"""
        entry = _OrderedEntry(plugin_id, self._next_order(), handler)
        self._recall_hooks.append(entry)
        return Registration(lambda: _remove_entry(self._recall_hooks, entry))

    async def run_outgoing_message_filters(
        self,
        target: ChatTarget,
        elements: Sequence[MessageElement],
    ) -> tuple[ChatTarget, Sequence[MessageElement]] | None:
        """顺序执行出站消息过滤器；任一阶段返回 None 则整体中止。"""
        current_target = target
        current_elements: Sequence[MessageElement] = elements
        for entry in self._message_filters:
            try:
                result = await _maybe_await(entry.handler(current_target, current_elements))
            except Exception:
                logger.exception("出站消息过滤器异常: plugin=%s", entry.plugin_id)
                continue
            if result is None:
                return None
            current_target, current_elements = result
        return current_target, current_elements

    async def run_outgoing_file_filters(
        self,
        target: ChatTarget,
        path: str,
        filename: str | None,
    ) -> tuple[ChatTarget, str, str | None] | None:
        """顺序执行出站文件过滤器；任一阶段返回 None 则整体中止。"""
        current_target = target
        current_path = path
        current_filename = filename
        for entry in self._file_filters:
            try:
                result = await _maybe_await(entry.handler(current_target, current_path, current_filename))
            except Exception:
                logger.exception("出站文件过滤器异常: plugin=%s", entry.plugin_id)
                continue
            if result is None:
                return None
            current_target, current_path, current_filename = result
        return current_target, current_path, current_filename

    async def run_before_recall_hooks(self, target: ChatTarget, seq: int) -> bool:
        """顺序执行撤回前置钩子；任一返回 False 表示禁止撤回。"""
        for entry in self._recall_hooks:
            try:
                result = await _maybe_await(entry.handler(target, seq))
            except Exception:
                logger.exception("撤回前置钩子异常: plugin=%s", entry.plugin_id)
                continue
            if result is False:
                return False
        return True

    # ---- 插件消息段 ----

    def register_element(
        self,
        plugin_id: str,
        element_type: str,
        *,
        renderer: ElementRenderer | None = None,
        sender: ElementSender | None = None,
    ) -> Registration:
        """注册某插件自己的消息段扩展。"""
        entry = _ElementEntry(plugin_id, renderer, sender)
        key = (plugin_id, element_type)
        self._elements[key] = entry

        def dispose() -> None:
            if self._elements.get(key) is entry:
                del self._elements[key]

        return Registration(dispose)

    def render_plugin_element(self, element: PluginElement) -> Any:
        """调用已注册渲染器；未注册、未提供或异常时返回 None。"""
        entry = self._elements.get((element.plugin_id, element.element_type))
        if entry is None or entry.renderer is None:
            return None
        try:
            return entry.renderer(element)
        except Exception:
            logger.exception("插件消息段渲染失败: %s/%s", element.plugin_id, element.element_type)
            return None

    async def convert_plugin_element(
        self,
        target: ChatTarget,
        element: PluginElement,
    ) -> tuple[Any, MessageElement]:
        """调用已注册发送器，返回协议元素与持久化领域元素。"""
        entry = self._elements.get((element.plugin_id, element.element_type))
        if entry is None or entry.sender is None:
            raise RuntimeError(f"插件消息段缺少发送器: {element.plugin_id}/{element.element_type}")
        try:
            result = await _maybe_await(entry.sender(target, element))
            return result
        except Exception as exc:
            logger.exception(
                "插件消息段发送失败: %s/%s",
                element.plugin_id,
                element.element_type,
            )
            raise RuntimeError(f"插件消息段发送失败: {element.plugin_id}/{element.element_type}") from exc

    # ---- 清理 ----

    def remove_plugin(self, plugin_id: str) -> None:
        """卸载插件时移除其全部注册，避免残留回调继续执行。"""
        self._message_filters = [entry for entry in self._message_filters if entry.plugin_id != plugin_id]
        self._file_filters = [entry for entry in self._file_filters if entry.plugin_id != plugin_id]
        self._recall_hooks = [entry for entry in self._recall_hooks if entry.plugin_id != plugin_id]
        for key in [key for key in self._elements if key[0] == plugin_id]:
            self._elements.pop(key, None)

    def _next_order(self) -> int:
        order = self._order
        self._order += 1
        return order


def _remove_entry(entries: list[_OrderedEntry], entry: _OrderedEntry) -> None:
    with contextlib.suppress(ValueError):
        entries.remove(entry)


async def _maybe_await(value: object) -> Any:
    """兼容插件自由选择同步或异步实现。"""
    if inspect.isawaitable(value):
        return await value
    return value
