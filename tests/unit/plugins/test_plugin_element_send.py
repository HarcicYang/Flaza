"""插件消息段到协议发送器的转换测试。"""

import asyncio

from flaza.core.models import FriendChat, PluginElement, TextElement
from flaza.plugins.registry import PluginExtensionRegistry
from flaza.qq.clients import LagrangeQQClient


def test_prepare_outgoing_element_uses_registered_sender() -> None:
    async def scenario() -> None:
        registry = PluginExtensionRegistry()

        async def sender(target, element):
            return "protocol-card", TextElement(text="持久化预览")

        registry.register_element("demo", "card", sender=sender)
        client = object.__new__(LagrangeQQClient)
        client._plugin_registry = registry

        chat = FriendChat(uid="u_1", uin=10001)
        element = PluginElement(plugin_id="demo", element_type="card", payload={"x": 1})
        protocol, domain = await client._prepare_outgoing_element(chat, element)

        assert protocol == "protocol-card"
        assert isinstance(domain, TextElement)
        assert domain.text == "持久化预览"

    asyncio.run(scenario())


def test_prepare_outgoing_element_requires_registry() -> None:
    async def scenario() -> None:
        client = object.__new__(LagrangeQQClient)
        client._plugin_registry = None

        chat = FriendChat(uid="u_1", uin=10001)
        element = PluginElement(plugin_id="demo", element_type="card")
        try:
            await client._prepare_outgoing_element(chat, element)
        except RuntimeError as exc:
            assert "发送器未注册" in str(exc)
        else:
            raise AssertionError("未注册发送器时应抛 RuntimeError")

    asyncio.run(scenario())
