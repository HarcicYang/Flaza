"""会话仓库：从消息表派生会话摘要。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite

from flaza.core.models import ChatTarget, FriendChat, GroupChat, Session

if TYPE_CHECKING:
    from flaza.core.storage.database import Storage


class SessionRepository:
    """读取由 messages、friends、groups 和 read_cursors 派生的会话列表。"""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    @property
    def _db(self) -> aiosqlite.Connection:
        return self._storage.require_db()

    async def list_recent(self, limit: int = 100) -> list[Session]:
        """返回最近会话，按最后一条消息的本地 id 倒序。"""
        cursor = await self._db.execute(
            """
            SELECT
                s.chat_kind       AS chat_kind,
                s.chat_id         AS chat_id,
                s.message_count   AS message_count,
                s.last_message_id AS last_message_id,
                s.last_timestamp  AS last_timestamp,
                m.text            AS last_text,
                f.uin             AS friend_uin,
                f.nickname        AS friend_nickname,
                f.remark          AS friend_remark,
                g.name            AS group_name,
                g.member_count    AS group_member_count,
                COALESCE(
                    (
                        SELECT COUNT(*)
                        FROM messages AS um
                        WHERE um.chat_kind = s.chat_kind
                          AND um.chat_id = s.chat_id
                          AND um.id > COALESCE(r.last_read_id, 0)
                    ),
                    0
                ) AS unread_count
            FROM session_stats AS s
            JOIN messages AS m ON m.id = s.last_message_id
            LEFT JOIN friends AS f ON s.chat_kind = 'friend' AND f.uid = s.chat_id
            LEFT JOIN groups AS g ON s.chat_kind = 'group' AND g.group_id = CAST(s.chat_id AS INTEGER)
            LEFT JOIN read_cursors AS r ON r.chat_kind = s.chat_kind AND r.chat_id = s.chat_id
            ORDER BY s.last_message_id DESC
            LIMIT ?
            """,
            (max(0, limit),),
        )
        rows = await cursor.fetchall()
        return [self._row_to_session(row) for row in rows]

    async def unread_count(self, chat: ChatTarget) -> int:
        """返回指定会话的未读数量。"""
        cursor = await self._db.execute(
            """
            SELECT COUNT(*) AS unread_count
            FROM messages AS m
            LEFT JOIN read_cursors AS r ON r.chat_kind = m.chat_kind AND r.chat_id = m.chat_id
            WHERE m.chat_kind = ? AND m.chat_id = ?
              AND m.id > COALESCE(r.last_read_id, 0)
            """,
            (chat.kind, chat.storage_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return 0
        return int(row["unread_count"])

    @staticmethod
    def _row_to_session(row: aiosqlite.Row) -> Session:
        chat_kind = row["chat_kind"]
        chat_id = row["chat_id"]
        if chat_kind == "friend":
            chat: ChatTarget = FriendChat(
                uid=chat_id,
                uin=int(row["friend_uin"] or 0),
            )
            title = row["friend_remark"] or row["friend_nickname"] or chat_id
        else:
            chat = GroupChat(group_id=int(chat_id))
            title = row["group_name"] or chat_id

        return Session(
            chat=chat,
            title=title,
            last_text=row["last_text"],
            last_timestamp=int(row["last_timestamp"]),
            last_message_id=int(row["last_message_id"]),
            message_count=int(row["message_count"]),
            unread_count=int(row["unread_count"]),
        )
