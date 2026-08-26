"""示例插件：收到撤回事件时保留本地消息内容。

插件通过 ``ctx.before_event`` 在核心服务处理 ``MessageRecalled`` 之前
拦截事件；示例选择吞掉事件（返回 ``None``），因此内置撤回灰条不会覆盖
保留内容，界面由插件直接从存储刷新。
"""

from __future__ import annotations

from flaza.core.events import MessageRecalled
from flaza.core.models import TextElement
from flaza.plugins import FlazaPlugin, PluginContext


class RecallKeep(FlazaPlugin):
    def __init__(self) -> None:
        self.ctx: PluginContext | None = None
        self.marker = ""

    async def on_load(self, context: PluginContext) -> None:
        self.ctx = context
        self.marker = str(context.get_setting("marker", "（已撤回）"))
        context.before_event(MessageRecalled, self._on_message_recalled)

    async def _on_message_recalled(self, event: MessageRecalled) -> None:
        context = self.ctx
        if context is None:
            return event

        stored = await context.runtime.storage.messages.get_by_seq(event.chat, event.seq)
        if stored is None:
            return event

        message = stored.message
        elements = list(message.elements)
        marker = self.marker.strip()
        if marker:
            elements = [TextElement(text=marker), *elements]

        await context.runtime.storage.messages.replace_message(
            message.model_copy(
                update={
                    "elements": elements,
                    "recalled": True,
                    "retain_content_on_recall": True,
                }
            )
        )

        state = context.runtime.state
        active = state.active_chat()
        if active is not None and active.key == event.chat.key:
            messages = await context.runtime.storage.messages.list_recent(event.chat)
            state.messages.set(tuple(messages))
        await state.refresh_sessions()
        return None


plugin = RecallKeep()
