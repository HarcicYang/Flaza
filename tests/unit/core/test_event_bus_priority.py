"""事件总线优先级与前置/后置订阅测试。"""

import asyncio

from flaza.core.events import EventBus, MessageReceived
from flaza.core.models import FriendChat, Message, TextElement


def _sample_message(text: str = "你好") -> Message:
    return Message(
        chat=FriendChat(uid="u_1", uin=10001),
        sender_uin=10001,
        sender_uid="u_1",
        seq=1,
        timestamp=1700000000,
        elements=[TextElement(text=text)],
    )


def test_event_bus_runs_higher_priority_first() -> None:
    async def scenario() -> None:
        bus = EventBus()
        order: list[str] = []
        done = asyncio.Event()

        async def low(event: MessageReceived) -> None:
            order.append("low")

        async def high(event: MessageReceived) -> None:
            order.append("high")
            done.set()

        bus.subscribe(MessageReceived, low, priority=-10)
        bus.subscribe(MessageReceived, high, priority=100)
        task = asyncio.create_task(bus.run())
        bus.publish(MessageReceived(message=_sample_message()))
        await asyncio.wait_for(done.wait(), timeout=1)
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert order == ["high", "low"]

    asyncio.run(scenario())


def test_before_handler_can_swallow_event() -> None:
    async def scenario() -> None:
        bus = EventBus()
        order: list[str] = []

        async def before(event: MessageReceived) -> MessageReceived | None:
            order.append("before")
            return None

        async def normal(event: MessageReceived) -> None:
            order.append("normal")

        bus.subscribe_before(MessageReceived, before)
        bus.subscribe(MessageReceived, normal)
        task = asyncio.create_task(bus.run())
        bus.publish(MessageReceived(message=_sample_message()))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert order == ["before"]

    asyncio.run(scenario())


def test_before_handler_can_replace_event() -> None:
    async def scenario() -> None:
        bus = EventBus()
        seen: list[str] = []
        done = asyncio.Event()

        async def before(event: MessageReceived) -> MessageReceived:
            return event.model_copy(update={"message": _sample_message("改写后")})

        async def normal(event: MessageReceived) -> None:
            seen.append(event.message.text)
            done.set()

        bus.subscribe_before(MessageReceived, before)
        bus.subscribe(MessageReceived, normal)
        task = asyncio.create_task(bus.run())
        bus.publish(MessageReceived(message=_sample_message()))
        await asyncio.wait_for(done.wait(), timeout=1)
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert seen == ["改写后"]

    asyncio.run(scenario())


def test_after_handler_runs_after_normal_handlers() -> None:
    async def scenario() -> None:
        bus = EventBus()
        order: list[str] = []
        done = asyncio.Event()

        async def normal(event: MessageReceived) -> None:
            order.append("normal")

        async def after(event: MessageReceived) -> None:
            order.append("after")
            done.set()

        bus.subscribe(MessageReceived, normal)
        bus.subscribe_after(MessageReceived, after)
        task = asyncio.create_task(bus.run())
        bus.publish(MessageReceived(message=_sample_message()))
        await asyncio.wait_for(done.wait(), timeout=1)
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert order == ["normal", "after"]

    asyncio.run(scenario())
