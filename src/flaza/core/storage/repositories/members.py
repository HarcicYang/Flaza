"""群成员身份缓存仓库。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import aiosqlite

from flaza.core.models import GroupMember, GroupMemberRole

if TYPE_CHECKING:
    from flaza.core.storage.database import Storage


class GroupMemberRepository:
    """缓存群成员 uin / 昵称 / 身份。"""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    @property
    def _db(self) -> aiosqlite.Connection:
        return self._storage.require_db()

    async def upsert(self, member: GroupMember) -> None:
        await self._db.execute(
            """
            INSERT INTO group_members (group_id, uid, uin, nickname, role, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (group_id, uid) DO UPDATE SET
                uin = excluded.uin,
                nickname = excluded.nickname,
                role = excluded.role,
                updated_at = excluded.updated_at
            """,
            (member.group_id, member.uid, member.uin, member.nickname, member.role.value, int(time.time())),
        )
        await self._db.commit()

    async def remove(self, group_id: int, uid: str) -> None:
        await self._db.execute("DELETE FROM group_members WHERE group_id = ? AND uid = ?", (group_id, uid))
        await self._db.commit()

    async def set_role(self, group_id: int, uid: str, role: GroupMemberRole) -> None:
        await self._db.execute(
            """
            UPDATE group_members SET role = ?, updated_at = ? WHERE group_id = ? AND uid = ?
            """,
            (role.value, int(time.time()), group_id, uid),
        )
        await self._db.commit()

    async def list_by_group(self, group_id: int) -> list[GroupMember]:
        cursor = await self._db.execute(
            "SELECT group_id, uid, uin, nickname, role FROM group_members WHERE group_id = ?",
            (group_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_member(row) for row in rows]

    async def get(self, group_id: int, uid: str) -> GroupMember | None:
        cursor = await self._db.execute(
            "SELECT group_id, uid, uin, nickname, role FROM group_members WHERE group_id = ? AND uid = ?",
            (group_id, uid),
        )
        row = await cursor.fetchone()
        return self._row_to_member(row) if row is not None else None

    @staticmethod
    def _row_to_member(row: aiosqlite.Row) -> GroupMember:
        return GroupMember(
            group_id=int(row["group_id"]),
            uid=row["uid"],
            uin=int(row["uin"] or 0),
            nickname=row["nickname"],
            role=GroupMemberRole(row["role"]),
        )
