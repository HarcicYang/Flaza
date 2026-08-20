"""消息仓库：写入、去重、分页与已读游标。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite

from flaza.core.models import ChatTarget, GroupChat, Message, MessageReaction, StoredMessage
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
                (chat_kind, chat_id, sender_uin, seq, client_seq, rand, timestamp, from_self, recalled, text, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                int(message.recalled),
                message.text,
                encode_message(message),
            ),
        )
        await self._db.commit()
        if isinstance(message.chat, GroupChat):
            await self._apply_pending_reactions(message.chat, message.seq)

        cursor = await self._db.execute(
            "SELECT id FROM messages WHERE chat_kind = ? AND chat_id = ? AND seq = ?",
            (chat_kind, chat_id, message.seq),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("消息写入后无法定位")
        return int(row["id"])

    async def list_recent(self, chat: ChatTarget, limit: int = 50) -> list[StoredMessage]:
        """返回最近 limit 条消息，按时间正序（可直接用于聊天流）。"""
        return await self._list_latest(chat, limit, before_id=None)

    async def list_before(self, chat: ChatTarget, before_id: int, limit: int = 50) -> list[StoredMessage]:
        """返回指定本地 id 之前的更早消息，按时间正序。"""
        return await self._list_latest(chat, limit, before_id=before_id)

    async def has_before(self, chat: ChatTarget, before_id: int) -> bool:
        """返回指定本地 id 之前是否还有更早消息。"""
        chat_kind, chat_id = _chat_columns(chat)
        cursor = await self._db.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM messages
                WHERE chat_kind = ? AND chat_id = ? AND id < ?
            ) AS has_before
            """,
            (chat_kind, chat_id, before_id),
        )
        row = await cursor.fetchone()
        return row is not None and bool(row["has_before"])

    async def list_after(self, chat: ChatTarget, after_id: int, limit: int = 100) -> list[StoredMessage]:
        """返回指定本地 id 之后的消息，按时间正序。"""
        chat_kind, chat_id = _chat_columns(chat)
        cursor = await self._db.execute(
            "SELECT id, payload FROM messages WHERE chat_kind = ? AND chat_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (chat_kind, chat_id, after_id, max(0, limit)),
        )
        rows = await cursor.fetchall()
        return [StoredMessage(id=int(row["id"]), message=decode_message(row["payload"])) for row in rows]

    async def update_payload(self, message: Message) -> Message | None:
        """只替换同会话同 seq 消息的元素，保留当前 recalled 等字段。

        媒体缓存写回时不能覆盖并发发生的撤回状态，因此先读出当前
        payload，再用新 elements 重建后写回；返回实际持久化的模型。
        """
        chat_kind, chat_id = _chat_columns(message.chat)
        cursor = await self._db.execute(
            "SELECT payload FROM messages WHERE chat_kind = ? AND chat_id = ? AND seq = ?",
            (chat_kind, chat_id, message.seq),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        current = decode_message(row["payload"])
        merged = current.model_copy(update={"elements": message.elements})
        cursor = await self._db.execute(
            "UPDATE messages SET text = ?, payload = ? WHERE chat_kind = ? AND chat_id = ? AND seq = ?",
            (
                merged.text,
                encode_message(merged),
                chat_kind,
                chat_id,
                message.seq,
            ),
        )
        await self._db.commit()
        return merged if cursor.rowcount > 0 else None

    async def apply_group_reaction(
        self,
        chat: ChatTarget,
        seq: int,
        emoji_id: str,
        emoji_type: int,
        count: int,
        *,
        is_increase: bool,
        operator_uid: str,
    ) -> StoredMessage | None:
        """合并一条群表情事件并立即持久化。

        此方法不依赖 UI 当前是否打开该群，因此启动同步期间收到的回应
        也会写入本地消息 payload，供之后进入会话时恢复。
        """
        chat_kind, chat_id = _chat_columns(chat)
        cursor = await self._db.execute(
            "SELECT id, payload FROM messages WHERE chat_kind = ? AND chat_id = ? AND seq = ?",
            (chat_kind, chat_id, seq),
        )
        row = await cursor.fetchone()
        if row is None:
            await self._store_pending_reaction(
                chat,
                seq,
                emoji_id,
                emoji_type,
                count,
                is_increase=is_increase,
                operator_uid=operator_uid,
            )
            return None

        current = decode_message(row["payload"])
        reactions = list(current.reactions)
        for index, reaction in enumerate(reactions):
            if reaction.emoji_id == emoji_id and reaction.emoji_type == emoji_type:
                users = set(reaction.users)
                if is_increase:
                    users.add(operator_uid)
                else:
                    users.discard(operator_uid)
                reactions[index] = reaction.model_copy(update={"count": max(0, count), "users": sorted(users)})
                break
        else:
            if not is_increase or count <= 0:
                return StoredMessage(id=int(row["id"]), message=current)
            reactions.append(
                MessageReaction(
                    emoji_id=emoji_id,
                    emoji_type=emoji_type,
                    count=count,
                    users=[operator_uid],
                )
            )

        merged = current.model_copy(update={"reactions": reactions})
        await self._db.execute(
            "UPDATE messages SET payload = ? WHERE chat_kind = ? AND chat_id = ? AND seq = ?",
            (encode_message(merged), chat_kind, chat_id, seq),
        )
        await self._db.commit()
        return StoredMessage(id=int(row["id"]), message=merged)

    async def _store_pending_reaction(
        self,
        chat: ChatTarget,
        seq: int,
        emoji_id: str,
        emoji_type: int,
        count: int,
        *,
        is_increase: bool,
        operator_uid: str,
    ) -> None:
        if not isinstance(chat, GroupChat):
            return
        await self._db.execute(
            """
            INSERT INTO pending_group_reactions
                (group_id, seq, emoji_id, emoji_type, count, is_increase, operator_uid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (group_id, seq, emoji_id, emoji_type) DO UPDATE SET
                count = excluded.count,
                is_increase = excluded.is_increase,
                operator_uid = excluded.operator_uid
            """,
            (chat.group_id, seq, emoji_id, emoji_type, count, int(is_increase), operator_uid),
        )
        await self._db.commit()

    async def _apply_pending_reactions(self, chat: GroupChat, seq: int) -> None:
        cursor = await self._db.execute(
            """
            SELECT emoji_id, emoji_type, count, is_increase, operator_uid
            FROM pending_group_reactions
            WHERE group_id = ? AND seq = ?
            """,
            (chat.group_id, seq),
        )
        pending = await cursor.fetchall()
        if not pending:
            return
        for row in pending:
            await self.apply_group_reaction(
                chat,
                seq,
                str(row["emoji_id"]),
                int(row["emoji_type"]),
                int(row["count"]),
                is_increase=bool(row["is_increase"]),
                operator_uid=str(row["operator_uid"]),
            )
        await self._db.execute(
            "DELETE FROM pending_group_reactions WHERE group_id = ? AND seq = ?",
            (chat.group_id, seq),
        )
        await self._db.commit()

    async def mark_recalled(self, chat: ChatTarget, seq: int) -> bool:
        """把指定消息标记为已撤回，返回是否更新成功。"""
        chat_kind, chat_id = _chat_columns(chat)
        cursor = await self._db.execute(
            "SELECT payload FROM messages WHERE chat_kind = ? AND chat_id = ? AND seq = ?",
            (chat_kind, chat_id, seq),
        )
        row = await cursor.fetchone()
        if row is None:
            return False

        message = decode_message(row["payload"])
        if message.recalled:
            return True
        updated = message.model_copy(update={"recalled": True})
        cursor = await self._db.execute(
            "UPDATE messages SET recalled = 1, payload = ? WHERE chat_kind = ? AND chat_id = ? AND seq = ?",
            (encode_message(updated), chat_kind, chat_id, seq),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def latest_seq(self, chat: ChatTarget) -> int | None:
        """返回会话最后一条消息的协议 seq。"""
        chat_kind, chat_id = _chat_columns(chat)
        cursor = await self._db.execute(
            "SELECT MAX(seq) AS latest_seq FROM messages WHERE chat_kind = ? AND chat_id = ?",
            (chat_kind, chat_id),
        )
        row = await cursor.fetchone()
        if row is None or row["latest_seq"] is None:
            return None
        return int(row["latest_seq"])

    async def latest_id(self, chat: ChatTarget) -> int | None:
        """返回会话最后一条消息的本地 id。"""
        chat_kind, chat_id = _chat_columns(chat)
        cursor = await self._db.execute(
            "SELECT MAX(id) AS latest_id FROM messages WHERE chat_kind = ? AND chat_id = ?",
            (chat_kind, chat_id),
        )
        row = await cursor.fetchone()
        if row is None or row["latest_id"] is None:
            return None
        return int(row["latest_id"])

    async def get_by_seq(self, chat: ChatTarget, seq: int) -> StoredMessage | None:
        """按会话和协议 seq 查询单条消息。"""
        chat_kind, chat_id = _chat_columns(chat)
        cursor = await self._db.execute(
            "SELECT id, payload FROM messages WHERE chat_kind = ? AND chat_id = ? AND seq = ?",
            (chat_kind, chat_id, seq),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return StoredMessage(id=int(row["id"]), message=decode_message(row["payload"]))

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

    async def _list_latest(
        self,
        chat: ChatTarget,
        limit: int,
        *,
        before_id: int | None,
    ) -> list[StoredMessage]:
        """取最近 limit 条（可选 before_id 之前），再按 id 正序返回。"""
        chat_kind, chat_id = _chat_columns(chat)
        if before_id is None:
            cursor = await self._db.execute(
                """
                SELECT id, payload FROM (
                    SELECT id, payload FROM messages
                    WHERE chat_kind = ? AND chat_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC
                """,
                (chat_kind, chat_id, max(0, limit)),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT id, payload FROM (
                    SELECT id, payload FROM messages
                    WHERE chat_kind = ? AND chat_id = ? AND id < ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC
                """,
                (chat_kind, chat_id, before_id, max(0, limit)),
            )
        rows = await cursor.fetchall()
        return [StoredMessage(id=int(row["id"]), message=decode_message(row["payload"])) for row in rows]
