"""插件扩展注册表测试。"""

import asyncio
from collections.abc import Sequence

from flaza.core.models import (
    ChatTarget,
    FriendChat,
    Message,
    MessageElement,
    PluginElement,
    StoredMessage,
    TextElement,
)
from flaza.plugins.registry import PluginExtensionRegistry


def _chat() -> FriendChat:
    return FriendChat(uid="u_1", uin=10001)


def _stored() -> StoredMessage:
    return StoredMessage(
        id=1,
        message=Message(
            chat=_chat(),
            sender_uin=10001,
            sender_uid="u_1",
            seq=1,
            timestamp=1,
            elements=[TextElement(text="原文")],
        ),
    )


def test_message_filters_rewrite_then_abort() -> None:
    async def scenario() -> None:
        registry = PluginExtensionRegistry()
        calls: list[str] = []

        async def rewrite(
            target: ChatTarget,
            elements: Sequence[MessageElement],
        ) -> tuple[ChatTarget, Sequence[MessageElement]]:
            calls.append("rewrite")
            return target, [TextElement(text="改写")]

        async def abort(
            target: ChatTarget,
            elements: Sequence[MessageElement],
        ) -> tuple[ChatTarget, Sequence[MessageElement]] | None:
            calls.append("abort")
            return None

        registry.register_outgoing_message_filter("demo", rewrite)
        registry.register_outgoing_message_filter("demo", abort)

        assert await registry.run_outgoing_message_filters(_chat(), [TextElement(text="原文")]) is None
        assert calls == ["rewrite", "abort"]

    asyncio.run(scenario())


def test_message_filters_can_rewrite_target_and_elements() -> None:
    async def scenario() -> None:
        registry = PluginExtensionRegistry()
        original = _chat()

        async def redirect(
            target: ChatTarget,
            elements: Sequence[MessageElement],
        ) -> tuple[ChatTarget, Sequence[MessageElement]]:
            return target, [TextElement(text="被插件改写")]

        registry.register_outgoing_message_filter("demo", redirect)
        result = await registry.run_outgoing_message_filters(original, [TextElement(text="原文")])
        assert result is not None
        target, elements = result
        assert target == original
        texts: list[str] = []
        for element in elements:
            assert isinstance(element, TextElement)
            texts.append(element.text)
        assert texts == ["被插件改写"]

    asyncio.run(scenario())


def test_filter_exception_is_isolated_and_dispose_removes_handler() -> None:
    async def scenario() -> None:
        registry = PluginExtensionRegistry()

        async def broken(target: ChatTarget, elements: Sequence[MessageElement]) -> None:
            raise RuntimeError("boom")

        registration = registry.register_outgoing_message_filter("demo", broken)
        result = await registry.run_outgoing_message_filters(_chat(), [])
        assert result is not None
        assert result[1] == []

        registration.dispose()
        # 覆盖 dispose 后再跑一次，过滤器已不存在，结果仍为原样。
        assert await registry.run_outgoing_message_filters(_chat(), []) is not None

    asyncio.run(scenario())


def test_file_filter_and_recall_hook() -> None:
    async def scenario() -> None:
        registry = PluginExtensionRegistry()
        chat = _chat()

        async def lock_file(target: ChatTarget, path: str, filename: str | None) -> None:
            return None

        async def fake_confirm(target: ChatTarget, seq: int) -> bool:
            return False

        registry.register_outgoing_file_filter("demo", lock_file)
        registry.register_before_recall_hook("demo", fake_confirm)

        assert await registry.run_outgoing_file_filters(chat, "/tmp/a.txt", "a.txt") is None
        assert await registry.run_before_recall_hooks(chat, 10) is False

    asyncio.run(scenario())


def test_element_renderer_and_sender_roundtrip() -> None:
    async def scenario() -> None:
        registry = PluginExtensionRegistry()
        element = PluginElement(plugin_id="demo", element_type="card", payload={"x": 1})

        registry.register_element(
            "demo",
            "card",
            renderer=lambda item: f"render:{item.payload['x']}",
            sender=lambda target, item: ("protocol", item),
        )

        assert registry.render_plugin_element(element) == "render:1"
        protocol, domain = await registry.convert_plugin_element(_chat(), element)
        assert protocol == "protocol"
        assert domain == element

    asyncio.run(scenario())


def test_element_fallbacks_and_sender_errors() -> None:
    async def scenario() -> None:
        registry = PluginExtensionRegistry()
        element = PluginElement(plugin_id="demo", element_type="unknown")

        assert registry.render_plugin_element(element) is None

        unknown = PluginElement(plugin_id="demo", element_type="broken")
        registry.register_element("demo", "broken", renderer=lambda item: 1 / 0)
        assert registry.render_plugin_element(unknown) is None

        try:
            await registry.convert_plugin_element(_chat(), element)
        except RuntimeError as exc:
            assert "缺少发送器" in str(exc)
        else:
            raise AssertionError("缺少发送器时应抛 RuntimeError")

    asyncio.run(scenario())


def test_remove_plugin_cleans_all_registrations() -> None:
    async def scenario() -> None:
        registry = PluginExtensionRegistry()
        chat = _chat()

        async def keep(
            target: ChatTarget,
            elements: Sequence[MessageElement],
        ) -> tuple[ChatTarget, Sequence[MessageElement]]:
            return target, elements

        async def keep_file(
            target: ChatTarget,
            path: str,
            filename: str | None,
        ) -> tuple[ChatTarget, str, str | None]:
            return target, path, filename

        async def block_recall(target: ChatTarget, seq: int) -> bool:
            return False

        registry.register_outgoing_message_filter("demo", keep)
        registry.register_outgoing_file_filter("demo", keep_file)
        registry.register_before_recall_hook("demo", block_recall)
        registry.register_element("demo", "card", renderer=lambda item: "card")

        async def plugin_action(item: StoredMessage) -> None:
            return None

        registry.register_message_action("demo", "send", plugin_action, label="+1")

        registry.remove_plugin("demo")

        assert await registry.run_outgoing_message_filters(chat, []) is not None
        assert (await registry.run_outgoing_file_filters(chat, "p", None)) is not None
        assert await registry.run_before_recall_hooks(chat, 1) is True
        assert registry.render_plugin_element(PluginElement(plugin_id="demo", element_type="card")) is None
        assert await registry.run_message_action("demo", "send", _stored()) is False

    asyncio.run(scenario())


def test_message_action_registration_dispatch_and_dispose() -> None:
    async def scenario() -> None:
        registry = PluginExtensionRegistry()
        stored = _stored()
        seen: list[int] = []

        async def handler(item: StoredMessage) -> None:
            seen.append(item.id)

        registration = registry.register_message_action("demo", "send", handler, label="+1")
        actions = registry.message_actions()
        assert len(actions) == 1
        assert actions[0].label == "+1"
        assert actions[0].key == "plugin:demo:send"

        assert await registry.run_message_action("demo", "send", stored) is True
        assert seen == [1]

        registration.dispose()
        assert registry.message_actions() == ()
        assert await registry.run_message_action("demo", "send", stored) is False

    asyncio.run(scenario())


def test_message_action_exception_is_isolated() -> None:
    async def scenario() -> None:
        registry = PluginExtensionRegistry()

        async def broken(_item: StoredMessage) -> None:
            raise RuntimeError("boom")

        registry.register_message_action("demo", "send", broken)
        assert await registry.run_message_action("demo", "send", _stored()) is False

    asyncio.run(scenario())
