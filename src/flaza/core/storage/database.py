"""异步 SQLite 存储入口。

参考 EulerOneBot 的 InfoManager：单连接 aiosqlite、sqlite3.Row 行工厂、
启动建表、repository 通过 require_db 获取连接。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Self

import aiosqlite

from flaza.core.storage.repositories.contacts import ContactRepository
from flaza.core.storage.repositories.members import GroupMemberRepository
from flaza.core.storage.repositories.messages import MessageRepository
from flaza.core.storage.repositories.sessions import SessionRepository

_SCHEMA = """
CREATE TABLE IF NOT EXISTS friends (
    uid         TEXT PRIMARY KEY,
    uin         INTEGER NOT NULL UNIQUE,
    nickname    TEXT NOT NULL DEFAULT '',
    remark      TEXT,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    group_id     INTEGER PRIMARY KEY,
    name         TEXT NOT NULL DEFAULT '',
    member_count INTEGER NOT NULL DEFAULT 0,
    owner_uid    TEXT,
    updated_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id   INTEGER NOT NULL,
    uid        TEXT NOT NULL,
    uin        INTEGER NOT NULL DEFAULT 0,
    nickname   TEXT NOT NULL DEFAULT '',
    role       TEXT NOT NULL DEFAULT 'member',
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (group_id, uid)
);

CREATE INDEX IF NOT EXISTS idx_group_members_group
    ON group_members (group_id);

CREATE TABLE IF NOT EXISTS read_cursors (
    chat_kind    TEXT NOT NULL,
    chat_id      TEXT NOT NULL,
    last_read_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_kind, chat_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_kind     TEXT NOT NULL,
    chat_id       TEXT NOT NULL,
    sender_uin    INTEGER NOT NULL,
    seq           INTEGER NOT NULL,
    client_seq    INTEGER,
    rand          INTEGER,
    timestamp     INTEGER NOT NULL,
    from_self     INTEGER NOT NULL DEFAULT 0,
    recalled      INTEGER NOT NULL DEFAULT 0,
    text          TEXT NOT NULL DEFAULT '',
    payload       BLOB NOT NULL,
    UNIQUE (chat_kind, chat_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_time
    ON messages (chat_kind, chat_id, timestamp DESC, id DESC);

CREATE TABLE IF NOT EXISTS pending_group_reactions (
    group_id     INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    emoji_id     TEXT NOT NULL,
    emoji_type   INTEGER NOT NULL,
    count        INTEGER NOT NULL,
    is_increase  INTEGER NOT NULL,
    operator_uid TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (group_id, seq, emoji_id, emoji_type)
);

DROP VIEW IF EXISTS session_stats;
CREATE VIEW session_stats AS
SELECT
    chat_kind,
    chat_id,
    COUNT(*)      AS message_count,
    MAX(id)       AS last_message_id,
    MAX(timestamp) AS last_timestamp
FROM messages
GROUP BY chat_kind, chat_id;
"""


class Storage:
    """Flaza 业务数据的异步 SQLite 存储。"""

    def __init__(self) -> None:
        self._db: aiosqlite.Connection | None = None
        self.contacts = ContactRepository(self)
        self.members = GroupMemberRepository(self)
        self.messages = MessageRepository(self)
        self.sessions = SessionRepository(self)

    async def init(self, path: str | Path = "flaza.db") -> Self:
        """打开数据库并建立表结构。"""
        if self._db is not None:
            return self

        database_path = Path(path)
        if database_path.parent != Path("."):
            database_path.parent.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(database_path)
        self._db.row_factory = sqlite3.Row
        await self._db.executescript(_SCHEMA)
        await self._migrate()
        await self._db.commit()
        return self

    async def close(self) -> None:
        """提交并关闭数据库连接。"""
        if self._db is None:
            return
        await self._db.commit()
        await self._db.close()
        self._db = None

    async def _migrate(self) -> None:
        """为旧版本数据库补充新增列。"""
        db = self._db
        assert db is not None

        async def has_column(table: str, column: str) -> bool:
            cursor = await db.execute(f"PRAGMA table_info({table})")
            rows = await cursor.fetchall()
            return any(row["name"] == column for row in rows)

        if await has_column("messages", "recalled") is False:
            await db.execute("ALTER TABLE messages ADD COLUMN recalled INTEGER NOT NULL DEFAULT 0")
        if await has_column("groups", "owner_uid") is False:
            await db.execute("ALTER TABLE groups ADD COLUMN owner_uid TEXT")

    def require_db(self) -> aiosqlite.Connection:
        """返回已初始化的连接；未初始化时抛出明确错误。"""
        if self._db is None:
            raise RuntimeError("Storage 尚未初始化，请先 await storage.init()")
        return self._db
