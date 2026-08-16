"""联系人服务：同步好友、群资料与群成员身份。"""

from __future__ import annotations

import asyncio
import logging

from flaza.core.events import ContactsUpdated, EventBus, GroupMembersUpdated
from flaza.core.models import GroupMember
from flaza.core.ports import QQClient
from flaza.core.storage import Storage

logger = logging.getLogger(__name__)


class ContactService:
    """从 QQ 协议拉取联系人并写入存储。"""

    def __init__(self, qq: QQClient, storage: Storage, bus: EventBus) -> None:
        self._qq = qq
        self._storage = storage
        self._bus = bus

    async def sync(self) -> None:
        """全量同步好友和群资料。"""
        friends = await self._qq.fetch_friends()
        groups = await self._qq.fetch_groups()

        for friend in friends:
            await self._storage.contacts.upsert_friend(friend)
        for group in groups:
            await self._storage.contacts.upsert_group(group)

        self._bus.publish(ContactsUpdated(friends=friends, groups=groups))

    async def ensure_member_roles(self, group_id: int, uids: list[str]) -> list[GroupMember]:
        """并行查询少量群成员身份，并写入缓存。"""
        if not uids:
            return []
        results = await asyncio.gather(
            *(self._qq.fetch_group_member(group_id, uid) for uid in uids),
            return_exceptions=True,
        )
        members: list[GroupMember] = []
        for result in results:
            if isinstance(result, GroupMember):
                members.append(result)
                await self._storage.members.upsert(result)
        return members

    async def sync_group_members(self) -> None:
        """后台同步全部群的成员身份缓存。"""
        all_members = []
        for group in await self._storage.contacts.list_groups():
            try:
                members = await self._qq.fetch_group_members(group.group_id)
            except Exception:
                logger.exception("群成员同步失败: %s", group.group_id)
                continue
            for member in members:
                await self._storage.members.upsert(member)
            all_members.extend(members)
        if all_members:
            self._bus.publish(GroupMembersUpdated(members=all_members))
