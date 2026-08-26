"""HomePage 插件快捷动作路由测试。"""

import asyncio

from flaza.app import build_application
from flaza.config import AppConfig
from flaza.core.models import FriendChat, Message, StoredMessage, TextElement
from flaza.ui.pages.home import HomePage


def test_home_routes_plugin_quick_action() -> None:
    async def scenario() -> None:
        config = AppConfig()
        _app, runtime = build_application(config)

        chat = FriendChat(uid="u_1", uin=10001)
        stored = StoredMessage(
            id=1,
            message=Message(
                chat=chat,
                sender_uin=10001,
                sender_uid="u_1",
                sender_name="小明",
                seq=1,
                timestamp=1,
                elements=[TextElement(text="你好")],
            ),
        )

        seen: list[int] = []

        async def handler(stored: StoredMessage) -> None:
            seen.append(stored.id)

        runtime.plugin_registry.register_message_action("demo", "send", handler, label="+1")
        home = HomePage(
            runtime.state,
            runtime.actions,
            runtime.bus,
            config,
            runtime.render,
            plugin_registry=runtime.plugin_registry,
        )
        await home._on_message_action("plugin:demo:send", stored)
        assert seen == [1]

    asyncio.run(scenario())
