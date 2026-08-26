"""recall-keep 示例插件集成测试。"""

import asyncio
import shutil
from pathlib import Path

from flaza.config import AppConfig, PathsConfig
from flaza.core.events import MessageRecalled
from flaza.core.models import FriendChat, Message, StoredMessage, TextElement
from flaza.plugins import PluginHost
from flaza.runtime import ApplicationRuntime

_EXAMPLE_PLUGIN = Path(__file__).resolve().parents[3] / "examples" / "plugins" / "recall-keep"


def _copy_example(tmp_path: Path) -> Path:
    plugins_dir = tmp_path / "plugins"
    shutil.copytree(_EXAMPLE_PLUGIN, plugins_dir / "recall-keep")
    return plugins_dir


def test_recall_keep_example_preserves_content_and_swallows_event(tmp_path: Path) -> None:
    async def scenario() -> None:
        plugins_dir = _copy_example(tmp_path)
        runtime = ApplicationRuntime(
            AppConfig(
                paths=PathsConfig(
                    plugins_dir=str(plugins_dir),
                    plugin_state_path=str(tmp_path / "plugin_state.json"),
                )
            )
        )
        await runtime.storage.init(tmp_path / "flaza.db")
        host = PluginHost(runtime)
        await host.start()
        assert host.loaded == ("recall-keep",)

        chat = FriendChat(uid="u_1", uin=10001)
        message = Message(
            chat=chat,
            sender_uin=10001,
            sender_uid="u_1",
            sender_name="小明",
            seq=1,
            timestamp=1,
            elements=[TextElement(text="这条内容不允许被撤回")],
        )
        await runtime.storage.messages.insert(message)
        runtime.state.active_chat.set(chat)
        runtime.state.messages.set(tuple(await runtime.storage.messages.list_recent(chat)))

        seen_after_plugin = []
        runtime.bus.subscribe(MessageRecalled, lambda event: seen_after_plugin.append(event.seq))
        bus_task = asyncio.create_task(runtime.bus.run())

        runtime.bus.publish(MessageRecalled(chat=chat, seq=1, timestamp=2))
        stored = await _wait_for_stored_message(runtime, chat)
        await _wait_until(
            lambda: (
                bool(runtime.state.messages())
                and runtime.state.messages()[0].message.recalled is True
                and runtime.state.messages()[0].message.retain_content_on_recall is True
            )
        )

        assert stored.message.recalled is True
        assert stored.message.retain_content_on_recall is True
        assert stored.message.text == "（已撤回）这条内容不允许被撤回"

        ui_message = runtime.state.messages()[0].message
        assert ui_message.recalled is True
        assert ui_message.retain_content_on_recall is True
        assert ui_message.text == stored.message.text

        await asyncio.sleep(0.02)
        assert seen_after_plugin == []

        bus_task.cancel()
        await asyncio.gather(bus_task, return_exceptions=True)
        await host.stop()
        await runtime.storage.close()

    asyncio.run(scenario())


def test_recall_keep_example_unknown_message_does_not_swallow(tmp_path: Path) -> None:
    async def scenario() -> None:
        plugins_dir = _copy_example(tmp_path)
        runtime = ApplicationRuntime(
            AppConfig(
                paths=PathsConfig(
                    plugins_dir=str(plugins_dir),
                    plugin_state_path=str(tmp_path / "plugin_state.json"),
                )
            )
        )
        await runtime.storage.init(tmp_path / "flaza.db")
        host = PluginHost(runtime)
        await host.start()

        chat = FriendChat(uid="u_1", uin=10001)
        seen: list[int] = []
        runtime.bus.subscribe(MessageRecalled, lambda event: seen.append(event.seq))
        bus_task = asyncio.create_task(runtime.bus.run())

        runtime.bus.publish(MessageRecalled(chat=chat, seq=999, timestamp=2))
        await _wait_until(lambda: seen == [999])

        bus_task.cancel()
        await asyncio.gather(bus_task, return_exceptions=True)
        await host.stop()
        await runtime.storage.close()

    asyncio.run(scenario())


async def _wait_for_stored_message(runtime: ApplicationRuntime, chat: FriendChat) -> StoredMessage:
    for _ in range(100):
        stored = await runtime.storage.messages.get_by_seq(chat, 1)
        if stored is not None and stored.message.recalled:
            return stored
        await asyncio.sleep(0.01)
    raise AssertionError("recall-keep 插件未处理撤回事件")


async def _wait_until(predicate) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("等待超时")
