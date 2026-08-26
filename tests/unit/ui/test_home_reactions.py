"""HomePage 表情回应本地更新测试。"""

import asyncio
from pathlib import Path

from flaza.app import build_application
from flaza.config import AppConfig
from flaza.core.models import GroupChat, Message, SelfInfo, TextElement
from flaza.ui.pages.home import HomePage


class _FakeQQ:
    def __init__(self) -> None:
        self.sent: list[tuple[object, int, str, int, bool]] = []

    async def send_reaction(
        self,
        chat: object,
        seq: int,
        emoji_id: str,
        emoji_type: int = 2,
        is_cancel: bool = False,
    ) -> None:
        self.sent.append((chat, seq, emoji_id, emoji_type, is_cancel))


def test_sent_reaction_updates_open_chat_immediately(tmp_path: Path) -> None:
    async def scenario() -> None:
        config = AppConfig(login={"uin": 123, "signer_url": "https://sign.example.com"})
        _app, runtime = build_application(config)
        await runtime.storage.init(tmp_path / "flaza.db")
        qq = _FakeQQ()
        runtime._qq = qq  # type: ignore[attr-defined]

        chat = GroupChat(group_id=20001)
        await runtime.storage.messages.insert(
            Message(
                chat=chat,
                sender_uin=10001,
                sender_uid="u_1",
                seq=1,
                timestamp=1,
                elements=[TextElement(text="你好")],
            )
        )
        state = runtime.state
        state.self_info.set(SelfInfo(uin=123, uid="u_self", nickname="我"))
        state.active_chat.set(chat)
        state.messages.set(tuple(await runtime.storage.messages.list_recent(chat)))

        home = HomePage(state, runtime.actions, runtime.bus, config, runtime.render)
        stored = state.messages()[0]
        await home._on_reaction_selected(stored, "😊", 2, False)

        assert qq.sent == [(chat, 1, "😊", 2, False)]
        updated = state.messages()[0]
        assert updated.message.reactions[0].emoji_id == "😊"
        assert updated.message.reactions[0].count == 1
        assert updated.message.reactions[0].users == ["u_self"]
        reloaded = await runtime.storage.messages.list_recent(chat)
        assert reloaded[0].message.reactions[0].count == 1
        await runtime.storage.close()

    asyncio.run(scenario())
