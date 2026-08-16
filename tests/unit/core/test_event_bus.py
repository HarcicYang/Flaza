"""事件总线单元测试。"""

import asyncio

from flaza.core.events import EventBus, MessageReceived
from flaza.core.models import FriendChat, Message, TextElement


def _sample_message() -> Message:
    return Message(
        chat=FriendChat(uid="u_1", uin=10001),
        sender_uin=10001,
        sender_uid="u_1",
        seq=1,
        timestamp=1700000000,
        elements=[TextElement(text="你好")],
    )


def test_event_bus_dispatches_in_subscription_order() -> None:
    async def scenario() -> None:
        bus = EventBus()
        order: list[str] = []
        done = asyncio.Event()

        async def first(event: MessageReceived) -> None:
            order.append("first")
            done.set()

        async def second(event: MessageReceived) -> None:
            order.append("second")

        bus.subscribe(MessageReceived, first)
        bus.subscribe(MessageReceived, second)
        task = asyncio.create_task(bus.run())
        bus.publish(MessageReceived(message=_sample_message()))
        await asyncio.wait_for(done.wait(), timeout=1)
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert order == ["first", "second"]

    asyncio.run(scenario())


def test_event_bus_continues_after_handler_error() -> None:
    async def scenario() -> None:
        bus = EventBus()
        done = asyncio.Event()

        async def broken(event: MessageReceived) -> None:
            raise RuntimeError("boom")

        async def healthy(event: MessageReceived) -> None:
            done.set()

        bus.subscribe(MessageReceived, broken)
        bus.subscribe(MessageReceived, healthy)
        task = asyncio.create_task(bus.run())
        bus.publish(MessageReceived(message=_sample_message()))
        await asyncio.wait_for(done.wait(), timeout=1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
