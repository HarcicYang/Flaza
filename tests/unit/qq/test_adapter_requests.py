"""事件适配层的申请/邀请事件测试。"""

import asyncio
from types import SimpleNamespace

from flaza.core.events import EventBus, RequestReceived, RequestResolved
from flaza.core.models import RequestKind
from flaza.qq.adapter import LagrangeEventAdapter


def test_friend_request_publishes_pending_request() -> None:
    async def scenario() -> None:
        bus = EventBus()
        received: list[RequestReceived] = []
        done = asyncio.Event()

        async def on_request(event: RequestReceived) -> None:
            received.append(event)
            done.set()

        bus.subscribe(RequestReceived, on_request)
        bus_task = asyncio.create_task(bus.run())
        adapter = LagrangeEventAdapter(bus)
        try:
            await adapter._on_friend_request(
                None,  # type: ignore[arg-type]
                SimpleNamespace(from_uin=10001, from_uid="u_1", message="我是小明"),
            )
            await asyncio.wait_for(done.wait(), timeout=1)
        finally:
            bus_task.cancel()
            await asyncio.gather(bus_task, return_exceptions=True)

        request = received[0].request
        assert request.kind is RequestKind.FRIEND
        assert request.key == "friend:u_1"
        assert request.target_uid == "u_1"
        assert request.subtitle == "我是小明"
        assert request.can_respond is True

    asyncio.run(scenario())


def test_friend_add_notify_resolves_and_refreshes_contacts() -> None:
    async def scenario() -> None:
        bus = EventBus()
        resolved: list[RequestResolved] = []
        done = asyncio.Event()

        async def on_resolved(event: RequestResolved) -> None:
            resolved.append(event)
            done.set()

        bus.subscribe(RequestResolved, on_resolved)
        bus_task = asyncio.create_task(bus.run())
        adapter = LagrangeEventAdapter(bus)
        try:
            await adapter._on_friend_add_notify(
                None,  # type: ignore[arg-type]
                SimpleNamespace(from_uin=10001, from_uid="u_1", status=0),
            )
            await asyncio.wait_for(done.wait(), timeout=1)
        finally:
            bus_task.cancel()
            await asyncio.gather(bus_task, return_exceptions=True)

        assert resolved[0].key == "friend:u_1"
        assert resolved[0].accepted is True
        assert resolved[0].refresh_contacts is True

    asyncio.run(scenario())


def test_group_invite_publishes_placeholder_request() -> None:
    async def scenario() -> None:
        bus = EventBus()
        received: list[RequestReceived] = []
        done = asyncio.Event()

        async def on_request(event: RequestReceived) -> None:
            received.append(event)
            done.set()

        bus.subscribe(RequestReceived, on_request)
        bus_task = asyncio.create_task(bus.run())
        adapter = LagrangeEventAdapter(bus)
        try:
            await adapter._on_group_invite(
                None,  # type: ignore[arg-type]
                SimpleNamespace(grp_id=20002, invitor_uid="u_inv"),
            )
            await asyncio.wait_for(done.wait(), timeout=1)
        finally:
            bus_task.cancel()
            await asyncio.gather(bus_task, return_exceptions=True)

        request = received[0].request
        assert request.kind is RequestKind.GROUP_INVITE
        assert request.key == "group-invite:20002"
        assert request.can_respond is False

    asyncio.run(scenario())
