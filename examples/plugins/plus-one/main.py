"""示例插件：复读 +1。

插件通过 ``register_message_action`` 在每条消息的气泡快捷动作区增加
“+1”按钮；点击后把原消息的完整元素序列原样发送到同一会话。
"""

from __future__ import annotations

from flaza.core.models import StoredMessage
from flaza.plugins import FlazaPlugin, PluginContext


class PlusOne(FlazaPlugin):
    def __init__(self) -> None:
        self.ctx: PluginContext | None = None

    async def on_load(self, context: PluginContext) -> None:
        self.ctx = context
        context.register_message_action("send", self._send_plus_one, label="+1")

    async def _send_plus_one(self, stored: StoredMessage) -> None:
        context = self.ctx
        if context is None:
            return
        message = stored.message
        await context.send_message(message.chat, list(message.elements))


plugin = PlusOne()
