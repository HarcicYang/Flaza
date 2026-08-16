"""消息仓库：写入、去重、分页与已读游标。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite

from flaza.core.models import ChatTarget, Message
from flaza.core.storage.codec import decode_message, encode_message

if TYPE_CHECKING:
    from flaza.core.storage.database import Storage


def _chat_columns(chat: ChatTarget) -> tuple[str, str]:
    """把会话目标映射为存储查询列。"""
    return chat.kind, chat.storage_id


class MessageRepository:
    """消息的持久化。"""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    @property
    def _db(self) -> aiosqlite.Connection:
        return self._storage.require_db()

    async def insert(self, message: Message) -> int:
        """写入消息并返回本地自增 id；重复消息返回已有 id。"""
        chat_kind, chat_id = _chat_columns(message.chat)
        await self._db.execute(
            """
            INSERT OR IGNORE INTO messages
                (chat_kind, chat_id, sender_uin, seq, client_seq, rand, timestamp, from_self, text, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_kind,
                chat_id,
                message.sender_uin,
                message.seq,
                message.client_seq,
                message.rand,
                message.timestamp,
                int(message.from_self),
                message.text,
                encode_message(message),
            ),
        )
        await self._db.commit()

        cursor = await self._db.execute(
            "SELECT id FROM messages WHERE chat_kind = ? AND chat_id = ? AND seq = ?",
            (chat_kind, chat_id, message.seq),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("消息写入后无法定位")
        return int(row["id"])

    async def list_recent(self, chat: ChatTarget, limit: int = 50) -> list[Message]:
        """返回最近 limit 条消息，按时间正序（可直接用于聊天流）。"""
        return await self._list(chat, "ORDER BY id ASC", limit)

    async def list_before(self, chat: ChatTarget, before_id: int, limit: int = 50) -> list[Message]:
        """返回指定本地 id 之前的更早消息，按时间正序。"""
        return await self._list(chat, "AND id < ? ORDER BY id ASC", limit, before_id)

    async def list_after(self, chat: ChatTarget, after_id: int, limit: int = 100) -> list[Message]:
        """返回指定本地 id 之后的消息，按时间正序。"""
        return await self._list(chat, "AND id > ? ORDER BY id ASC", limit, after_id)

    async def mark_read(self, chat: ChatTarget, last_read_id: int) -> None:
        """更新会话已读游标，只允许向前推进。"""
        chat_kind, chat_id = _chat_columns(chat)
        await self._db.execute(
            """
            INSERT INTO read_cursors (chat_kind, chat_id, last_read_id)
            VALUES (?, ?, ?)
            ON CONFLICT (chat_kind, chat_id) DO UPDATE SET
                last_read_id = excluded.last_read_id
            WHERE read_cursors.last_read_id < excluded.last_read_id
            """,
            (chat_kind, chat_id, last_read_id),
        )
        await self._db.commit()

    async def _list(self, chat: ChatTarget, clause: str, limit: int, parameter: int | None = None) -> list[Message]:
        chat_kind, chat_id = _chat_columns(chat)
        params: tuple[object, ...]
        if parameter is None:
            params = (chat_kind, chat_id, max(0, limit))
        else:
            params = (chat_kind, chat_id, parameter, max(0, limit))
        cursor = await self._db.execute(
            f"SELECT payload FROM messages WHERE chat_kind = ? AND chat_id = ? {clause} LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [decode_message(row["payload"]) for row in rows]
