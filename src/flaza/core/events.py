"""领域事件与顺序事件总线。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

from flaza.core.models import (
    ChatTarget,
    ConnectionState,
    Friend,
    Group,
    GroupMember,
    LoginPhase,
    Message,
    QrCodeData,
    SelfInfo,
)

logger = logging.getLogger(__name__)


class FlazaEvent(BaseModel):
    """所有领域事件的基类。"""

    model_config = ConfigDict(frozen=True)


class LoginPhaseChanged(FlazaEvent):
    """登录阶段发生变化。"""

    phase: LoginPhase
    detail: str = ""


class QrCodeReady(FlazaEvent):
    """二维码已生成，可以展示给用户。"""

    qr: QrCodeData


class ConnectionStateChanged(FlazaEvent):
    """QQ 连接状态发生变化。"""

    state: ConnectionState
    detail: str = ""


class SelfInfoChanged(FlazaEvent):
    """当前账号信息已更新。"""

    info: SelfInfo


class MessageReceived(FlazaEvent):
    """收到一条新消息。"""

    message: Message


class MessageSent(FlazaEvent):
    """成功发送一条消息。"""

    message: Message


class MessageRecalled(FlazaEvent):
    """消息被撤回。"""

    chat: ChatTarget
    seq: int
    timestamp: int = 0
    operator_uid: str = ""


class GroupNameChanged(FlazaEvent):
    """群名变更。"""

    group_id: int
    name_new: str
    operator_uid: str = ""
    timestamp: int = 0


class GroupMemberJoined(FlazaEvent):
    """群成员加入。"""

    group_id: int
    uid: str
    uin: int = 0
    join_type: int = 0
    timestamp: int = 0


class GroupMemberQuit(FlazaEvent):
    """群成员退出或被移出。"""

    group_id: int
    uid: str
    uin: int = 0
    exit_type: int = 0
    operator_uid: str = ""
    timestamp: int = 0

    @property
    def is_kicked(self) -> bool:
        return self.exit_type in (3, 131)


class GroupAdminChanged(FlazaEvent):
    """群管理员设置变更。"""

    group_id: int
    uid: str
    is_set: bool
    timestamp: int = 0


class GroupMemberMuted(FlazaEvent):
    """群成员被禁言；target_uid 为空表示全员禁言。"""

    group_id: int
    operator_uid: str
    target_uid: str
    duration: int
    timestamp: int = 0


class GroupMembersUpdated(FlazaEvent):
    """群成员身份缓存更新完成。"""

    members: list[GroupMember]


class MessagesSynced(FlazaEvent):
    """启动时完成一次离线消息补拉。"""

    total: int = 0


class ContactsUpdated(FlazaEvent):
    """联系人数据完成一次同步。"""

    friends: list[Friend]
    groups: list[Group]


_E = TypeVar("_E", bound=FlazaEvent)
EventHandler = Callable[[_E], Awaitable[None]]


class Subscription:
    """事件订阅句柄，dispose 后不再接收事件。"""

    def __init__(self, bus: EventBus, event_type: type[FlazaEvent], handler: EventHandler[FlazaEvent]) -> None:
        self._bus = bus
        self._event_type = event_type
        self._handler = handler
        self._disposed = False

    def dispose(self) -> None:
        """退订事件，重复调用无副作用。"""
        if self._disposed:
            return
        self._bus._remove(self._event_type, self._handler)
        self._disposed = True


class EventBus:
    """同步入队、单消费者顺序派发的领域事件总线。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[FlazaEvent] = asyncio.Queue()
        self._handlers: dict[type[FlazaEvent], list[EventHandler[FlazaEvent]]] = defaultdict(list)

    def publish(self, event: FlazaEvent) -> None:
        """把事件放入队列，立即返回。"""
        self._queue.put_nowait(event)

    def subscribe(self, event_type: type[_E], handler: EventHandler[_E]) -> Subscription:
        """注册某类事件的异步处理器，同一处理器类型可注册多个。"""
        self._handlers[event_type].append(handler)  # type: ignore[arg-type]
        return Subscription(self, event_type, handler)  # type: ignore[arg-type]

    async def run(self) -> None:
        """消费队列并按注册顺序依次 await 处理器。

        任务被取消时停止；单个处理器异常只记录日志，不阻塞后续事件。
        """
        while True:
            event = await self._queue.get()
            for handler in self._handlers[type(event)]:
                try:
                    await handler(event)  # type: ignore[arg-type]
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("事件处理器执行失败: %r", event)

    def _remove(self, event_type: type[FlazaEvent], handler: EventHandler[FlazaEvent]) -> None:
        """移除一个已注册的处理器。"""
        handlers = self._handlers.get(event_type)
        if handlers is None:
            return
        with contextlib.suppress(ValueError):
            handlers.remove(handler)
