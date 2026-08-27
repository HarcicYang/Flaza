"""plus-one 示例插件行为测试。"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from flaza.core.events import EventBus
from flaza.core.models import ChatTarget, GroupChat, Message, MessageElement, StoredMessage, TextElement
from flaza.plugins import PluginContext
from flaza.plugins.host import PluginHost
from flaza.plugins.registry import PluginExtensionRegistry
from flaza.plugins.state import PluginState
from flaza.runtime import ApplicationRuntime

_EXAMPLE_PLUGIN = Path(__file__).resolve().parents[3] / "examples" / "plugins" / "plus-one"


def test_plus_one_example_sends_exact_elements() -> None:
    async def scenario() -> None:
        calls: list[tuple[ChatTarget, list[MessageElement]]] = []

        class FakeMessageService:
            async def send_message(
                self,
                target: ChatTarget,
                elements: list[MessageElement],
            ) -> Message:
                calls.append((target, list(elements)))
                return Message(
                    chat=target,
                    sender_uin=1,
                    sender_uid="u_me",
                    seq=99,
                    timestamp=2,
                    elements=list(elements),
                    from_self=True,
                )

        runtime = cast(ApplicationRuntime, SimpleNamespace(message_service=FakeMessageService()))
        registry = PluginExtensionRegistry()
        host = cast(PluginHost, SimpleNamespace(registry=registry))
        context = PluginContext("plus-one", runtime, EventBus(), PluginState(), host)

        plugin = _load_plugin()
        await plugin.on_load(context)

        chat = GroupChat(group_id=20001)
        elements = [TextElement(text="复读这条消息")]
        stored = StoredMessage(
            id=1,
            message=Message(
                chat=chat,
                sender_uin=10001,
                sender_uid="u_1",
                sender_name="小明",
                seq=1,
                timestamp=1,
                elements=elements,
            ),
        )

        assert registry.message_actions()[0].key == "plugin:plus-one:send"
        assert await registry.run_message_action("plus-one", "send", stored) is True
        assert calls == [(chat, elements)]

    asyncio.run(scenario())


def _load_plugin():
    module_name = "example_plus_one_under_test"
    spec = importlib.util.spec_from_file_location(module_name, _EXAMPLE_PLUGIN / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.plugin
