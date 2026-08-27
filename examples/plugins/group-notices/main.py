"""示例插件：群事件播报。

插件在核心内置灰条之前拦截群事件，避免出现重复提示，并自己驱动必要的
成员缓存更新，然后写入包含成员/群名称的详细通知。
"""

from __future__ import annotations

from flaza.core.events import (
    GroupAdminChanged,
    GroupMemberJoined,
    GroupMemberMuted,
    GroupMemberQuit,
    GroupNameChanged,
)
from flaza.core.models import GroupMember, GroupMemberRole
from flaza.plugins import FlazaPlugin, PluginContext


class GroupNotices(FlazaPlugin):
    def __init__(self) -> None:
        self.ctx: PluginContext | None = None

    async def on_load(self, context: PluginContext) -> None:
        self.ctx = context
        context.before_event(GroupMemberJoined, self._on_joined)
        context.before_event(GroupMemberQuit, self._on_quit)
        context.before_event(GroupAdminChanged, self._on_admin_changed)
        context.before_event(GroupMemberMuted, self._on_muted)
        context.before_event(GroupNameChanged, self._on_name_changed)

    async def _on_joined(self, event: GroupMemberJoined):
        context = self.ctx
        if context is None:
            return event
        name = await self._member_name(event.group_id, event.uid, event.uin)
        await context.runtime.storage.members.upsert(
            GroupMember(
                group_id=event.group_id,
                uid=event.uid,
                uin=event.uin,
                role=GroupMemberRole.MEMBER,
            )
        )
        await context.notify(
            f"group:{event.group_id}",
            f"{name} 加入了群聊",
            timestamp=event.timestamp,
            key=f"group-join:{event.group_id}:{event.uid}:{event.timestamp}",
        )
        return None

    async def _on_quit(self, event: GroupMemberQuit):
        context = self.ctx
        if context is None:
            return event
        name = await self._member_name(event.group_id, event.uid, event.uin)
        await context.runtime.storage.members.remove(event.group_id, event.uid)
        roles = dict(context.runtime.state.group_roles())
        roles.pop(f"{event.group_id}:{event.uid}", None)
        context.runtime.state.group_roles.set(roles)
        action = "被移出群聊" if event.is_kicked else "退出了群聊"
        await context.notify(
            f"group:{event.group_id}",
            f"{name} {action}",
            timestamp=event.timestamp,
            key=f"group-quit:{event.group_id}:{event.uid}:{event.timestamp}",
        )
        return None

    async def _on_admin_changed(self, event: GroupAdminChanged):
        context = self.ctx
        if context is None:
            return event
        name = await self._member_name(event.group_id, event.uid, 0)
        role = GroupMemberRole.ADMIN if event.is_set else GroupMemberRole.MEMBER
        member = await context.runtime.storage.members.get(event.group_id, event.uid)
        if member is None:
            await context.runtime.storage.members.upsert(GroupMember(group_id=event.group_id, uid=event.uid, role=role))
        else:
            await context.runtime.storage.members.set_role(event.group_id, event.uid, role)
        roles = dict(context.runtime.state.group_roles())
        roles[f"{event.group_id}:{event.uid}"] = role
        context.runtime.state.group_roles.set(roles)
        action = "被设置为管理员" if event.is_set else "被取消管理员"
        await context.notify(
            f"group:{event.group_id}",
            f"{name} {action}",
            timestamp=event.timestamp,
            key=f"group-admin:{event.group_id}:{event.uid}:{event.timestamp}",
        )
        return None

    async def _on_muted(self, event: GroupMemberMuted):
        context = self.ctx
        if context is None:
            return event
        if event.target_uid:
            name = await self._member_name(event.group_id, event.target_uid, 0)
            text = f"{name} 被禁言 {event.duration} 秒"
        else:
            text = "开启了全员禁言"
        await context.notify(
            f"group:{event.group_id}",
            text,
            timestamp=event.timestamp,
            key=f"group-mute:{event.group_id}:{event.target_uid}:{event.timestamp}",
        )
        return None

    async def _on_name_changed(self, event: GroupNameChanged):
        context = self.ctx
        if context is None:
            return event
        await context.runtime.storage.contacts.update_group_name(event.group_id, event.name_new)
        groups = [
            (group.model_copy(update={"name": event.name_new}) if group.group_id == event.group_id else group)
            for group in context.runtime.state.groups()
        ]
        context.runtime.state.groups.set(tuple(groups))
        await context.runtime.state.refresh_sessions()
        await context.notify(
            f"group:{event.group_id}",
            f"群名已修改为“{event.name_new}”",
            timestamp=event.timestamp,
            key=f"group-name:{event.group_id}:{event.timestamp}",
        )
        return None

    async def _member_name(self, group_id: int, uid: str, uin: int) -> str:
        context = self.ctx
        if context is None:
            return str(uin or uid)
        member = await context.runtime.storage.members.get(group_id, uid)
        if member is not None and member.nickname:
            return member.nickname
        return str(uin or uid)


plugin = GroupNotices()
