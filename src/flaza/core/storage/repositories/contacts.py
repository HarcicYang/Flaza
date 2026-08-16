"""联系人与群资料仓库。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import aiosqlite

from flaza.core.models import Friend, Group

if TYPE_CHECKING:
    from flaza.core.storage.database import Storage


class ContactRepository:
    """好友和群资料的持久化。"""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    @property
    def _db(self) -> aiosqlite.Connection:
        return self._storage.require_db()

    async def upsert_friend(self, friend: Friend) -> None:
        """插入或更新一个好友资料。"""
        await self._db.execute(
            """
            INSERT INTO friends (uid, uin, nickname, remark, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (uid) DO UPDATE SET
                uin = excluded.uin,
                nickname = excluded.nickname,
                remark = excluded.remark,
                updated_at = excluded.updated_at
            """,
            (friend.uid, friend.uin, friend.nickname, friend.remark, int(time.time())),
        )
        await self._db.commit()

    async def upsert_group(self, group: Group) -> None:
        """插入或更新一个群资料。"""
        await self._db.execute(
            """
            INSERT INTO groups (group_id, name, member_count, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (group_id) DO UPDATE SET
                name = excluded.name,
                member_count = excluded.member_count,
                updated_at = excluded.updated_at
            """,
            (group.group_id, group.name, group.member_count, int(time.time())),
        )
        await self._db.commit()

    async def list_friends(self) -> list[Friend]:
        """返回全部好友资料。"""
        cursor = await self._db.execute("SELECT uid, uin, nickname, remark FROM friends ORDER BY uin")
        rows = await cursor.fetchall()
        return [Friend(uid=row["uid"], uin=row["uin"], nickname=row["nickname"], remark=row["remark"]) for row in rows]

    async def list_groups(self) -> list[Group]:
        """返回全部群资料。"""
        cursor = await self._db.execute("SELECT group_id, name, member_count FROM groups ORDER BY group_id")
        rows = await cursor.fetchall()
        return [Group(group_id=row["group_id"], name=row["name"], member_count=row["member_count"]) for row in rows]
