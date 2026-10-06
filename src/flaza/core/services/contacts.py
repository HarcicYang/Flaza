"""联系人服务：同步好友、群资料与群成员身份。"""

from __future__ import annotations

import asyncio
import logging

from flaza.core.events import ContactsUpdated, EventBus, GroupMembersUpdated
from flaza.core.models import GroupMember
from flaza.core.ports import QQClient
from flaza.core.storage import Storage

logger = logging.getLogger(__name__)

_GROUP_SYNC_CONCURRENCY = 3


class ContactService:
    """从 QQ 协议拉取联系人并写入存储。"""

    def __init__(self, qq: QQClient, storage: Storage, bus: EventBus) -> None:
        self._qq = qq
        self._storage = storage
        self._bus = bus

    async def sync(self) -> None:
        """全量同步好友和群资料。"""
        friends, groups = await asyncio.gather(
            self._qq.fetch_friends(),
            self._qq.fetch_groups(),
        )

        await self._storage.contacts.upsert_friends(friends)
        await self._storage.contacts.upsert_groups(groups)

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
        """后台并发同步全部群的成员身份缓存。"""
        groups = await self._storage.contacts.list_groups()
        semaphore = asyncio.Semaphore(_GROUP_SYNC_CONCURRENCY)

        async def sync_group(group_id: int) -> list[GroupMember]:
            async with semaphore:
                return await self._qq.fetch_group_members(group_id)

        results = await asyncio.gather(
            *(sync_group(group.group_id) for group in groups),
            return_exceptions=True,
        )
        all_members: list[GroupMember] = []
        for group, result in zip(groups, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("群成员同步失败: %s: %r", group.group_id, result)
                continue
            await self._storage.members.upsert_many(result)
            all_members.extend(result)
        if all_members:
            self._bus.publish(GroupMembersUpdated(members=all_members))
