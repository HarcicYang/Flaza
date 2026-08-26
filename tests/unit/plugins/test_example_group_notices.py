"""group-notices 示例插件行为测试。"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from flaza.core.events import (
    EventBus,
    GroupAdminChanged,
    GroupMemberJoined,
    GroupMemberMuted,
    GroupMemberQuit,
    GroupNameChanged,
)
from flaza.core.models import Group, GroupMember, GroupMemberRole
from flaza.plugins import PluginContext
from flaza.plugins.registry import PluginExtensionRegistry
from flaza.plugins.state import PluginState

_EXAMPLE_PLUGIN = Path(__file__).resolve().parents[3] / "examples" / "plugins" / "group-notices"


def test_group_notices_example_replaces_builtin_gray_notices(tmp_path: Path) -> None:
    async def scenario() -> None:
        members = _FakeMembers()
        contacts = _FakeContacts()
        state = _FakeStateStore()
        runtime = _FakeRuntime(state, members, contacts)
        registry = PluginExtensionRegistry()
        host = SimpleNamespace(registry=registry)
        bus = EventBus()
        context = PluginContext("group-notices", runtime, bus, PluginState(), host)

        plugin = _load_plugin()
        await plugin.on_load(context)
        assert len(context.subscriptions) == 5

        seen: list[str] = []

        async def record_normal(_event: Any) -> None:
            seen.append(type(_event).__name__)

        for event_type in (
            GroupMemberJoined,
            GroupMemberQuit,
            GroupAdminChanged,
            GroupMemberMuted,
            GroupNameChanged,
        ):
            bus.subscribe(event_type, record_normal)

        bus_task = asyncio.create_task(bus.run())

        bus.publish(GroupMemberJoined(group_id=20001, uid="u_new", uin=30001, timestamp=10))
        await _wait_for_notice(state, "30001 加入了群聊")
        member = await members.get(20001, "u_new")
        assert member is not None
        assert member.uin == 30001
        assert member.role == GroupMemberRole.MEMBER

        await members.upsert(
            GroupMember(
                group_id=20001,
                uid="u_admin",
                uin=20002,
                nickname="管理员",
                role=GroupMemberRole.MEMBER,
            )
        )
        bus.publish(GroupAdminChanged(group_id=20001, uid="u_admin", is_set=True, timestamp=11))
        await _wait_for_notice(state, "管理员 被设置为管理员")
        member = await members.get(20001, "u_admin")
        assert member is not None
        assert member.role == GroupMemberRole.ADMIN
        assert state.group_roles()["20001:u_admin"] == GroupMemberRole.ADMIN

        bus.publish(
            GroupMemberMuted(
                group_id=20001,
                operator_uid="u_op",
                target_uid="u_admin",
                duration=60,
                timestamp=12,
            )
        )
        await _wait_for_notice(state, "管理员 被禁言 60 秒")

        state.groups.set(
            (
                Group(group_id=20001, name="旧群名"),
            )
        )
        bus.publish(GroupNameChanged(group_id=20001, name_new="新群名", timestamp=13))
        await _wait_for_notice(state, "群名已修改为“新群名”")
        assert contacts.group_names[20001] == "新群名"
        assert state.groups()[0].name == "新群名"
        assert state.refresh_calls > 0
        assert runtime.render_calls > 0

        bus.publish(GroupMemberQuit(group_id=20001, uid="u_new", uin=30001, timestamp=14))
        await _wait_for_notice(state, "30001 退出了群聊")
        assert await members.get(20001, "u_new") is None

        await asyncio.sleep(0.02)
        assert seen == []

        bus_task.cancel()
        await asyncio.gather(bus_task, return_exceptions=True)

    asyncio.run(scenario())


class _FakeSignal:
    def __init__(self, initial: Any) -> None:
        self._value = initial

    def __call__(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        self._value = value


class _FakeMembers:
    def __init__(self) -> None:
        self._members: dict[tuple[int, str], GroupMember] = {}

    async def upsert(self, member: GroupMember) -> None:
        self._members[(member.group_id, member.uid)] = member

    async def get(self, group_id: int, uid: str) -> GroupMember | None:
        return self._members.get((group_id, uid))

    async def remove(self, group_id: int, uid: str) -> None:
        self._members.pop((group_id, uid), None)

    async def set_role(self, group_id: int, uid: str, role: GroupMemberRole) -> None:
        member = self._members.get((group_id, uid))
        if member is not None:
            self._members[(group_id, uid)] = member.model_copy(update={"role": role})


class _FakeContacts:
    def __init__(self) -> None:
        self.group_names: dict[int, str] = {}

    async def update_group_name(self, group_id: int, name: str) -> None:
        self.group_names[group_id] = name


class _FakeStateStore:
    def __init__(self) -> None:
        self.notices = _FakeSignal(tuple())
        self.group_roles = _FakeSignal({})
        self.groups = _FakeSignal(())
        self.refresh_calls = 0

    async def refresh_sessions(self) -> None:
        self.refresh_calls += 1


class _FakeRuntime:
    def __init__(
        self,
        state: _FakeStateStore,
        members: _FakeMembers,
        contacts: _FakeContacts,
    ) -> None:
        self.state = state
        self.storage = SimpleNamespace(members=members, contacts=contacts)
        self.render_calls = 0

    async def render(self) -> None:
        self.render_calls += 1


async def _wait_for_notice(state: _FakeStateStore, text: str) -> None:
    for _ in range(100):
        if any(notice.text == text for notice in state.notices()):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"group-notices 未写入通知: {text}")


def _load_plugin():
    module_name = "example_group_notices_under_test"
    spec = importlib.util.spec_from_file_location(module_name, _EXAMPLE_PLUGIN / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.plugin
