"""lagrange 事件订阅与领域事件转换。

lagrange 的 Events 每个事件类型只允许一个订阅者，因此这里统一订阅，
再通过领域 EventBus 在 Flaza 内部 fan-out。
"""

from __future__ import annotations

import logging
from typing import Any

from lagrange.client.client import Client
from lagrange.client.events.friend import FriendMessage
from lagrange.client.events.group import GroupMessage
from lagrange.client.events.service import ClientOffline, ClientOnline, ServerKick

from flaza.core.events import ConnectionStateChanged, EventBus, MessageReceived
from flaza.core.models import ConnectionState
from flaza.qq.convert import friend_message_to_domain, group_message_to_domain

logger = logging.getLogger(__name__)


class LagrangeEventAdapter:
    """把 lagrange 事件转换为 Flaza 领域事件。"""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._client: Client | None = None

    def subscribe(self, client: Client) -> None:
        """注册所有 MVP 所需的 lagrange 事件。"""
        self._client = client
        client.events.subscribe(FriendMessage, self._on_friend_message)
        client.events.subscribe(GroupMessage, self._on_group_message)
        client.events.subscribe(ClientOnline, self._on_client_online)
        client.events.subscribe(ClientOffline, self._on_client_offline)
        client.events.subscribe(ServerKick, self._on_server_kick)

    @property
    def client(self) -> Client:
        if self._client is None:
            raise RuntimeError("LagrangeEventAdapter 尚未订阅")
        return self._client

    async def _on_friend_message(self, client: Client, event: Any) -> None:
        message = friend_message_to_domain(event, client.uin)
        logger.debug("收到好友消息: chat=%s seq=%s", message.chat.key, message.seq)
        self._bus.publish(MessageReceived(message=message))

    async def _on_group_message(self, client: Client, event: Any) -> None:
        message = group_message_to_domain(event, client.uin)
        logger.debug("收到群消息: chat=%s seq=%s", message.chat.key, message.seq)
        self._bus.publish(MessageReceived(message=message))

    async def _on_client_online(self, _client: Client, _event: Any) -> None:
        self._bus.publish(ConnectionStateChanged(state=ConnectionState.ONLINE))

    async def _on_client_offline(self, _client: Client, event: Any) -> None:
        state = ConnectionState.RECONNECTING if event.recoverable else ConnectionState.OFFLINE
        self._bus.publish(ConnectionStateChanged(state=state))

    async def _on_server_kick(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            ConnectionStateChanged(
                state=ConnectionState.KICKED,
                detail=f"{event.title}: {event.tips}",
            )
        )
