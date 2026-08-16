"""群事件服务：把结构化群事件写入存储。"""

from __future__ import annotations

from flaza.core.events import (
    GroupAdminChanged,
    GroupMemberJoined,
    GroupMemberQuit,
    GroupNameChanged,
)
from flaza.core.models import GroupMember, GroupMemberRole
from flaza.core.storage import Storage


class GroupEventService:
    """处理需要持久化的群状态事件。"""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    async def on_group_name_changed(self, event: GroupNameChanged) -> None:
        await self._storage.contacts.update_group_name(event.group_id, event.name_new)

    async def on_group_member_joined(self, event: GroupMemberJoined) -> None:
        await self._storage.members.upsert(
            GroupMember(
                group_id=event.group_id,
                uid=event.uid,
                uin=event.uin,
                role=GroupMemberRole.MEMBER,
            )
        )

    async def on_group_member_quit(self, event: GroupMemberQuit) -> None:
        await self._storage.members.remove(event.group_id, event.uid)

    async def on_group_admin_changed(self, event: GroupAdminChanged) -> None:
        role = GroupMemberRole.ADMIN if event.is_set else GroupMemberRole.MEMBER
        if await self._storage.members.get(event.group_id, event.uid) is None:
            await self._storage.members.upsert(GroupMember(group_id=event.group_id, uid=event.uid, role=role))
        else:
            await self._storage.members.set_role(event.group_id, event.uid, role)
