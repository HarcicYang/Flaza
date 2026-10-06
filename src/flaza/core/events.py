"""领域事件与顺序事件总线。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict

from flaza.core.models import (
    ChatTarget,
    ConnectionState,
    Friend,
    Group,
    GroupMember,
    LoginPhase,
    Message,
    OnlineClient,
    PendingRequest,
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


class MessageMediaCached(FlazaEvent):
    """消息中的媒体已下载到本地缓存。"""

    message: Message


class MessageRecalled(FlazaEvent):
    """消息被撤回。"""

    chat: ChatTarget
    seq: int
    timestamp: int = 0
    operator_uid: str = ""


class FriendPoked(FlazaEvent):
    """好友戳一戳。"""

    sender_uin: int
    sender_uid: str = ""
    target_uin: int = 0
    action: str = ""
    suffix: str = ""
    timestamp: int = 0


class GroupNudged(FlazaEvent):
    """群内戳一戳。"""

    group_id: int
    sender_uin: int
    target_uin: int = 0
    action: str = ""
    suffix: str = ""


class GroupNotice(FlazaEvent):
    """群内其它值得展示为灰条的事件。"""

    group_id: int
    text: str
    timestamp: int = 0
    key: str = ""
    kind: str = ""


class RequestReceived(FlazaEvent):
    """收到好友申请、入群申请或群邀请。"""

    request: PendingRequest


class RequestResolved(FlazaEvent):
    """申请/邀请被处理或状态变化，通知中心据此移除条目。"""

    key: str
    accepted: bool = True
    detail: str = ""
    refresh_contacts: bool = False


class OtherClientsUpdated(FlazaEvent):
    """同一账号的其它在线端发生变化。"""

    clients: list[OnlineClient]


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


class GroupReactionChanged(FlazaEvent):
    """群消息表情回应变更。"""

    group_id: int
    seq: int
    emoji_id: str
    emoji_type: int
    count: int
    is_increase: bool
    operator_uid: str


_E = TypeVar("_E", bound=FlazaEvent)
EventHandler = Callable[[_E], Awaitable[None]]
BeforeEventHandler = Callable[[_E], Awaitable[_E | None]]


@dataclass(frozen=True, slots=True)
class _HandlerEntry:
    """事件总线内部的一条处理器记录。"""

    priority: int
    order: int
    mode: str
    # Handlers are registered against concrete event subclasses, while the queue
    # exposes the common base during dispatch.
    handler: Callable[..., Awaitable[Any]]
    token: object


class Subscription:
    """事件订阅句柄，dispose 后不再接收事件。"""

    def __init__(self, bus: EventBus, event_type: type[FlazaEvent], token: object, handler: object) -> None:
        self._bus = bus
        self._event_type = event_type
        self._handler = handler
        self._token = token
        self._disposed = False

    def dispose(self) -> None:
        """退订事件，重复调用无副作用。"""
        if self._disposed:
            return
        self._bus._remove(self._event_type, self._token)
        self._disposed = True


class EventBus:
    """同步入队、单消费者顺序派发的领域事件总线。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[FlazaEvent] = asyncio.Queue()
        self._handlers: dict[type[FlazaEvent], list[_HandlerEntry]] = defaultdict(list)
        self._order = 0

    def publish(self, event: FlazaEvent) -> None:
        """把事件放入队列，立即返回。"""
        self._queue.put_nowait(event)

    def subscribe(self, event_type: type[_E], handler: EventHandler[_E], *, priority: int = 0) -> Subscription:
        """注册某类事件的异步处理器；数值大的优先级先执行，同优先级按注册顺序。"""
        return self._register(event_type, handler, "normal", priority)

    def subscribe_before(
        self,
        event_type: type[_E],
        handler: BeforeEventHandler[_E],
        *,
        priority: int = 100,
    ) -> Subscription:
        """注册前置处理器，可改写事件；返回 ``None`` 表示吞掉事件。"""
        return self._register(event_type, handler, "before", priority)

    def subscribe_after(
        self,
        event_type: type[_E],
        handler: EventHandler[_E],
        *,
        priority: int = -100,
    ) -> Subscription:
        """注册后置处理器，默认在普通处理器之后执行。"""
        return self._register(event_type, handler, "after", priority)

    def _register(
        self,
        event_type: type[_E],
        handler: Callable[[_E], Awaitable[Any]],
        mode: str,
        priority: int,
    ) -> Subscription:
        token = object()
        self._handlers[event_type].append(_HandlerEntry(priority, self._order, mode, handler, token))
        self._order += 1
        return Subscription(self, event_type, token, handler)  # type: ignore[arg-type]

    async def run(self) -> None:
        """消费队列并按优先级依次 await 处理器。

        任务被取消时停止；单个处理器异常只记录日志，不阻塞后续事件。
        """
        while True:
            event = await self._queue.get()
            entries = sorted(self._handlers[type(event)], key=_handler_sort_key)
            for entry in entries:
                result = None
                try:
                    result = await entry.handler(event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("事件处理器执行失败: %r", event)
                if entry.mode == "before":
                    if result is None:
                        break
                    if result is not event and isinstance(result, FlazaEvent):
                        event = result

    def _remove(self, event_type: type[FlazaEvent], token: object) -> None:
        """移除一个已注册的处理器。"""
        handlers = self._handlers.get(event_type)
        if handlers is None:
            return
        with contextlib.suppress(ValueError):
            handlers[:] = [entry for entry in handlers if entry.token is not token]


def _handler_sort_key(entry: _HandlerEntry) -> tuple[int, int]:
    """Stable dispatch order: higher priority first, then registration order."""
    return -entry.priority, entry.order
