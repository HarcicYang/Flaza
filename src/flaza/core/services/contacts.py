"""联系人服务：同步好友与群资料。"""

from __future__ import annotations

from flaza.core.events import ContactsUpdated, EventBus
from flaza.core.ports import QQClient
from flaza.core.storage import Storage


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
