"""会话列表与消息流的增量更新测试。"""

import asyncio

from neony.dom import DOMElement, DomEvent

from flaza.config import AppConfig
from flaza.core.models import FriendChat, Message, Session, StoredMessage, TextElement
from flaza.runtime import ApplicationRuntime
from flaza.ui.components.message_list import MessageList
from flaza.ui.components.session_list import SessionList
from flaza.ui.state import ChatNotice, UiStateStore


def _runtime_state() -> tuple[ApplicationRuntime, UiStateStore]:
    runtime = ApplicationRuntime(AppConfig())
    return runtime, runtime.state


def test_session_list_reuses_rows_on_repeated_set() -> None:
    _runtime, state = _runtime_state()
    sessions = SessionList(state, _runtime.actions)
    session = Session(
        chat=FriendChat(uid="u_1", uin=10001),
        title="小明",
        last_text="你好",
        last_timestamp=1,
        last_message_id=1,
    )
    sessions.set_sessions([session])
    first = sessions.root.container[0]

    sessions.set_sessions([session])
    assert len(sessions.root.container) == 1
    assert sessions.root.container[0] is first

    updated = session.model_copy(update={"title": "小明(备注)", "unread_count": 3})
    sessions.set_sessions([updated])
    assert len(sessions.root.container) == 1
    assert sessions.root.container[0] is first
    row = sessions._rows["session:friend:u_1"]
    assert row.badge_el is not None
    assert len(row.preview_row.container) == 2

    read = updated.model_copy(update={"unread_count": 0})
    sessions.set_sessions([read])
    assert row.badge_el is None
    assert len(row.preview_row.container) == 1


def test_session_list_adds_and_removes_only_changed_rows() -> None:
    _runtime, state = _runtime_state()
    sessions = SessionList(state, _runtime.actions)
    first = Session(chat=FriendChat(uid="u_1", uin=10001), title="一", last_timestamp=1, last_message_id=1)
    second = Session(chat=FriendChat(uid="u_2", uin=10002), title="二", last_timestamp=2, last_message_id=2)
    sessions.set_sessions([first, second])
    first_el = sessions.root.container[0]
    second_el = sessions.root.container[1]

    third = Session(chat=FriendChat(uid="u_3", uin=10003), title="三", last_timestamp=3, last_message_id=3)
    sessions.set_sessions([first, second, third])
    assert len(sessions.root.container) == 3
    assert sessions.root.container[0] is first_el
    assert sessions.root.container[1] is second_el
    third_el = sessions.root.container[2]

    sessions.set_sessions([second, third])
    assert len(sessions.root.container) == 2
    assert sessions.root.container[0] is second_el
    assert sessions.root.container[1] is third_el


def _message(chat: FriendChat, seq: int, text: str, local_id: int) -> StoredMessage:
    return StoredMessage(
        id=local_id,
        message=Message(
            chat=chat,
            sender_uin=chat.uin,
            sender_uid=chat.uid,
            seq=seq,
            timestamp=seq,
            elements=[TextElement(text=text)],
        ),
    )


def test_message_list_appends_new_message_without_rebuilding() -> None:
    _runtime, state = _runtime_state()
    messages = MessageList(state)
    chat = FriendChat(uid="u_1", uin=10001)
    old = (_message(chat, 1, "一", 1), _message(chat, 2, "二", 2))
    messages.set_messages(chat, old)
    old_els = [messages.root.container[0], messages.root.container[1]]

    new = (*old, _message(chat, 3, "三", 3))
    messages.set_messages(chat, new)
    assert len(messages.root.container) == 3
    assert messages.root.container[0] is old_els[0]
    assert messages.root.container[1] is old_els[1]


def test_message_list_prepends_older_messages_without_rebuilding() -> None:
    _runtime, state = _runtime_state()
    messages = MessageList(state)
    chat = FriendChat(uid="u_1", uin=10001)
    current = (_message(chat, 2, "二", 2), _message(chat, 3, "三", 3))
    messages.set_messages(chat, current)
    old_els = [messages.root.container[0], messages.root.container[1]]

    combined = (_message(chat, 1, "一", 1), *current)
    messages.set_messages(chat, combined)
    assert len(messages.root.container) == 3
    assert messages.root.container[1] is old_els[0]
    assert messages.root.container[2] is old_els[1]


def test_message_list_removes_placeholder_when_first_item_arrives() -> None:
    _runtime, state = _runtime_state()
    messages = MessageList(state)
    chat = FriendChat(uid="u_1", uin=10001)

    messages.set_messages(chat, (), ())
    first = messages.root.container[0]
    assert isinstance(first, DOMElement)
    assert first.key == "message-list-placeholder"

    notice = (ChatNotice(chat_key=chat.key, text="有成员加入群聊", timestamp=1, key="n1"),)
    messages.set_messages(chat, (), notice)
    keys = [child.key for child in messages.root.container if hasattr(child, "key")]
    assert keys == ["notice:n1"]
    assert messages._ordered_keys == ["notice:n1"]

    messages.set_messages(chat, (_message(chat, 1, "一", 1),), ())
    keys = [child.key for child in messages.root.container if hasattr(child, "key")]
    assert keys == ["message:1"]
    assert messages._ordered_keys == ["message:1"]


def test_message_list_scroll_top_triggers_older_load_once() -> None:
    _runtime, state = _runtime_state()
    state.has_older_messages.set(True)
    messages = MessageList(state)

    calls = 0

    async def load_older() -> None:
        nonlocal calls
        calls += 1

    handler = messages._make_scroll_handler(load_older)
    event = DomEvent(key="message-list", type="scroll", scroll_top=0)
    asyncio.run(handler(event))
    assert calls == 1


def test_message_list_scroll_top_ignores_when_no_older() -> None:
    _runtime, state = _runtime_state()
    state.has_older_messages.set(False)
    messages = MessageList(state)

    async def load_older() -> None:
        raise AssertionError("不应触发历史加载")

    handler = messages._make_scroll_handler(load_older)
    event = DomEvent(key="message-list", type="scroll", scroll_top=0)
    asyncio.run(handler(event))


def test_message_list_shift_keeps_shared_rows() -> None:
    _runtime, state = _runtime_state()
    messages = MessageList(state)
    chat = FriendChat(uid="u_1", uin=10001)
    first = (_message(chat, 1, "一", 1), _message(chat, 2, "二", 2), _message(chat, 3, "三", 3))
    messages.set_messages(chat, first)
    middle_el = messages.root.container[1]

    shifted = (_message(chat, 2, "二", 2), _message(chat, 3, "三", 3), _message(chat, 4, "四", 4))
    messages.set_messages(chat, shifted)
    assert len(messages.root.container) == 3
    assert messages.root.container[0] is middle_el


def test_message_bubble_preserves_newlines() -> None:
    _runtime, state = _runtime_state()
    messages = MessageList(state)
    chat = FriendChat(uid="u_1", uin=10001)
    stored = _message(chat, 1, "第一行\n第二行", 1)
    messages.set_messages(chat, (stored,))

    def has_pre_wrap(element: DOMElement) -> bool:
        if element.styles.white_space == "pre-wrap":
            return True
        return any(has_pre_wrap(child) for child in element.container if isinstance(child, DOMElement))

    root = messages.root.container[0]
    assert isinstance(root, DOMElement)
    assert has_pre_wrap(root)


def test_message_list_replaces_recalled_item_in_place() -> None:
    _runtime, state = _runtime_state()
    messages = MessageList(state)
    chat = FriendChat(uid="u_1", uin=10001)
    old = (_message(chat, 1, "一", 1), _message(chat, 2, "二", 2))
    messages.set_messages(chat, old)
    first_el = messages.root.container[0]
    second_el = messages.root.container[1]

    recalled = (
        StoredMessage(id=1, message=old[0].message.model_copy(update={"recalled": True})),
        old[1],
    )
    messages.set_messages(chat, recalled)
    assert len(messages.root.container) == 2
    assert messages.root.container[0] is not first_el
    assert messages.root.container[1] is second_el
