"""插件运行时上下文：稳定便利 API 与完整 ApplicationRuntime 访问。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

from flaza.core.events import (
    BeforeEventHandler,
    EventBus,
    EventHandler,
    FlazaEvent,
    Subscription,
)
from flaza.core.models import ChatTarget, Friend, Group, Message, MessageElement
from flaza.plugins.registry import (
    ElementRenderer,
    ElementSender,
    OutgoingFileFilter,
    OutgoingMessageFilter,
    PluginExtensionRegistry,
    RecallHook,
    Registration,
)
from flaza.plugins.state import PluginState
from flaza.ui.state import ChatNotice

if TYPE_CHECKING:
    from flaza.plugins.host import PluginHost
    from flaza.runtime import ApplicationRuntime

_E = TypeVar("_E", bound=FlazaEvent)


class PluginContext:
    """插件沙箱不存在；ctx.runtime 可访问应用的全部内部对象。"""

    def __init__(
        self,
        plugin_id: str,
        runtime: ApplicationRuntime,
        bus: EventBus,
        state: PluginState,
        host: PluginHost,
    ) -> None:
        self.plugin_id = plugin_id
        self.runtime = runtime
        self._bus = bus
        self._state = state
        self._host = host
        self._subscriptions: set[Subscription] = set()
        self._registrations: set[Registration] = set()

    @property
    def registry(self) -> PluginExtensionRegistry:
        """当前运行时的插件扩展注册表。"""
        return self._host.registry

    @property
    def bus(self) -> EventBus:
        return self._bus

    @property
    def state(self) -> PluginState:
        return self._state

    @property
    def subscriptions(self) -> set[Subscription]:
        return self._subscriptions

    # ---- 事件 ----

    def publish(self, event: FlazaEvent) -> None:
        """发布领域事件，包括插件自定义的 FlazaEvent 子类。"""
        self._bus.publish(event)

    def subscribe(
        self,
        event_type: type[_E],
        handler: EventHandler[_E],
        *,
        priority: int = 0,
    ) -> Subscription:
        """注册普通事件处理器；数值大的优先级先执行。"""
        subscription = self._bus.subscribe(event_type, handler, priority=priority)
        self._subscriptions.add(subscription)
        return subscription

    def before_event(
        self,
        event_type: type[_E],
        handler: BeforeEventHandler[_E],
        *,
        priority: int = 100,
    ) -> Subscription:
        """在普通处理器之前改写事件；返回 ``None`` 表示吞掉后续处理。"""
        subscription = self._bus.subscribe_before(event_type, handler, priority=priority)
        self._subscriptions.add(subscription)
        return subscription

    def after_event(
        self,
        event_type: type[_E],
        handler: EventHandler[_E],
        *,
        priority: int = -100,
    ) -> Subscription:
        """注册事件后置处理器，默认晚于普通处理器执行。"""
        subscription = self._bus.subscribe_after(event_type, handler, priority=priority)
        self._subscriptions.add(subscription)
        return subscription

    # ---- 消息过滤器与动作钩子 ----

    def filter_outgoing_message(self, handler: OutgoingMessageFilter) -> Registration:
        """注册出站消息过滤器；返回 None 表示中止发送。"""
        registration = self.registry.register_outgoing_message_filter(self.plugin_id, handler)
        self._registrations.add(registration)
        return registration

    def filter_outgoing_file(self, handler: OutgoingFileFilter) -> Registration:
        """注册出站文件过滤器；返回 None 表示中止发送。"""
        registration = self.registry.register_outgoing_file_filter(self.plugin_id, handler)
        self._registrations.add(registration)
        return registration

    def before_recall(self, handler: RecallHook) -> Registration:
        """注册用户主动撤回的前置钩子；返回 False 表示禁止撤回。"""
        registration = self.registry.register_before_recall_hook(self.plugin_id, handler)
        self._registrations.add(registration)
        return registration

    def register_element(
        self,
        element_type: str,
        *,
        renderer: ElementRenderer | None = None,
        sender: ElementSender | None = None,
    ) -> Registration:
        """注册本插件的消息段扩展；renderer 负责 UI，sender 负责协议发送。"""
        registration = self.registry.register_element(
            self.plugin_id,
            element_type,
            renderer=renderer,
            sender=sender,
        )
        self._registrations.add(registration)
        return registration

    # ---- 消息与联系人 ----

    async def send_message(self, target: ChatTarget, elements: Sequence[MessageElement]) -> Message:
        """通过消息服务发送任意元素组合；QQ 未启动时抛出 RuntimeError。"""
        service = self.runtime.message_service
        if service is None:
            raise RuntimeError("QQ 尚未启动，无法发送消息")
        return await service.send_message(target, elements)

    async def send_text(self, target: ChatTarget, text: str) -> Message:
        """发送纯文本消息。"""
        service = self.runtime.message_service
        if service is None:
            raise RuntimeError("QQ 尚未启动，无法发送消息")
        return await service.send_text(target, text)

    async def list_friends(self) -> list[Friend]:
        """列出本地好友资料缓存。"""
        return await self.runtime.storage.contacts.list_friends()

    async def list_groups(self) -> list[Group]:
        """列出本地群资料缓存。"""
        return await self.runtime.storage.contacts.list_groups()

    # ---- 状态与 KV ----

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._state.get_setting(self.plugin_id, key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._state.set_setting(self.plugin_id, key, value)

    def delete_setting(self, key: str) -> None:
        self._state.delete_setting(self.plugin_id, key)

    def kv_get(self, key: str, default: Any = None) -> Any:
        return self._state.kv_get(self.plugin_id, key, default)

    def kv_set(self, key: str, value: Any) -> None:
        self._state.kv_set(self.plugin_id, key, value)

    def kv_delete(self, key: str) -> None:
        self._state.kv_delete(self.plugin_id, key)

    # ---- 任务与 UI ----

    def spawn_task(self, awaitable: Awaitable[Any]) -> asyncio.Task[Any]:
        """托管一个后台任务，插件卸载时宿主会自动取消。"""
        return self._host.spawn_task(awaitable)

    async def notify(self, chat_key: str, text: str, *, timestamp: int | None = None, key: str | None = None) -> None:
        """向指定聊天流追加一条灰条通知。"""
        state = self.runtime.state
        notice = ChatNotice(
            chat_key=chat_key,
            text=text,
            timestamp=int(timestamp or time.time()),
            key=key or f"plugin:{self.plugin_id}:{len(state.notices())}",
        )
        state.notices.set((*state.notices(), notice))
        await self.runtime.render()
