"""Durable Telegram ingestion and daily batch operations.

This module deliberately has no Telegram HTTP or ADK dependencies.  The
continuous collector and the scheduled summarizer share it so that storing an
update, advancing the polling offset, claiming work, and completing work all
use the same SQLite semantics.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_MAX_BATCH_BYTES = 12_000

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    update_id      INTEGER NOT NULL,
    chat_id        INTEGER NOT NULL,
    message_id     INTEGER NOT NULL,
    sender_id      INTEGER NOT NULL,
    thread_id      INTEGER,
    sent_at        INTEGER NOT NULL,
    edited_at      INTEGER,
    kind           TEXT NOT NULL
                   CHECK (kind IN ('thought', 'action', 'unknown')),
    body           TEXT NOT NULL,
    content_type   TEXT NOT NULL,
    raw_json       TEXT NOT NULL,
    batch_id       TEXT,
    processed_at   INTEGER,
    UNIQUE(chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS messages_unprocessed
ON messages(processed_at, batch_id, sent_at);

CREATE TABLE IF NOT EXISTS batches (
    batch_id       TEXT PRIMARY KEY,
    created_at     INTEGER NOT NULL,
    message_count  INTEGER NOT NULL,
    summary        TEXT,
    tags_json      TEXT,
    processed_at   INTEGER
);
"""

_PREFIX_PATTERNS = (
    (
        "thought",
        re.compile(
            r"^\s*/(?:thought|t)(?:@\w+)?(?:\s+|$)(.*)$",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "action",
        re.compile(
            r"^\s*/(?:action|a)(?:@\w+)?(?:\s+|$)(.*)$",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "thought",
        re.compile(r"^\s*(?:thought|t)\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL),
    ),
    (
        "action",
        re.compile(r"^\s*(?:action|a)\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL),
    ),
)

_CONTENT_TYPES = (
    "text",
    "photo",
    "video",
    "voice",
    "audio",
    "document",
    "animation",
    "video_note",
    "sticker",
    "location",
    "contact",
    "poll",
)


def open_database(path: str | Path) -> sqlite3.Connection:
    """Open ``path``, create its parent directory, and ensure the schema."""

    database_path = str(path) if str(path) == ":memory:" else str(Path(path).expanduser())
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.executescript(SCHEMA)
    return connection


def get_next_offset(connection: sqlite3.Connection) -> int:
    """Return the first Telegram update ID that has not been consumed."""

    row = connection.execute("SELECT value FROM bot_state WHERE key = 'next_offset'").fetchone()
    return int(row[0]) if row else 0


def get_pending_high_watermark(connection: sqlite3.Connection) -> int | None:
    """Return the highest pending row ID visible at the start of a run."""

    row = connection.execute(
        "SELECT MAX(id) FROM messages WHERE processed_at IS NULL"
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def classify_message(
    message: Mapping[str, Any],
    thought_thread_id: int | None = None,
    action_thread_id: int | None = None,
) -> tuple[str, str]:
    """Classify a Telegram message by topic first, then by a text prefix."""

    thread_id = message.get("message_thread_id")
    original = str(message.get("text") or message.get("caption") or "")

    if thought_thread_id is not None and thread_id == thought_thread_id:
        return "thought", original.strip()
    if action_thread_id is not None and thread_id == action_thread_id:
        return "action", original.strip()

    for kind, pattern in _PREFIX_PATTERNS:
        if match := pattern.match(original):
            return kind, match.group(1).strip()
    return "unknown", original.strip()


def detect_content_type(message: Mapping[str, Any]) -> str:
    """Return the first recognized Bot API content field on ``message``."""

    for content_type in _CONTENT_TYPES:
        if content_type in message:
            return content_type
    return "other"


def _advance_offset(connection: sqlite3.Connection, update_id: int) -> None:
    """Advance the offset monotonically; replayed updates cannot move it back."""

    connection.execute(
        """
        INSERT INTO bot_state (key, value)
        VALUES ('next_offset', ?)
        ON CONFLICT(key)
        DO UPDATE SET value = CAST(
            MAX(CAST(bot_state.value AS INTEGER), CAST(excluded.value AS INTEGER))
            AS TEXT
        )
        """,
        (str(update_id + 1),),
    )


def store_update(
    connection: sqlite3.Connection,
    update: Mapping[str, Any],
    *,
    allowed_user_id: int,
    allowed_chat_id: int,
    thought_thread_id: int | None = None,
    action_thread_id: int | None = None,
) -> None:
    """Store one authorized update and atomically acknowledge its update ID.

    Ignored updates are acknowledged too, otherwise one unauthorized or
    irrelevant event would be returned forever.  Edits update only messages
    that have not yet joined a batch, keeping failed-batch retries stable.
    """

    update_id = int(update["update_id"])
    message = update.get("message") or update.get("edited_message")

    with connection:
        if message is not None:
            chat_id = int(message.get("chat", {}).get("id", 0))
            sender_id = int(message.get("from", {}).get("id", 0))
            authorized = chat_id == allowed_chat_id and sender_id == allowed_user_id

            if authorized:
                kind, body = classify_message(
                    message,
                    thought_thread_id=thought_thread_id,
                    action_thread_id=action_thread_id,
                )
                connection.execute(
                    """
                    INSERT INTO messages (
                        update_id,
                        chat_id,
                        message_id,
                        sender_id,
                        thread_id,
                        sent_at,
                        edited_at,
                        kind,
                        body,
                        content_type,
                        raw_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chat_id, message_id)
                    DO UPDATE SET
                        update_id    = excluded.update_id,
                        thread_id    = excluded.thread_id,
                        edited_at    = excluded.edited_at,
                        kind         = excluded.kind,
                        body         = excluded.body,
                        content_type = excluded.content_type,
                        raw_json     = excluded.raw_json
                    WHERE
                        messages.processed_at IS NULL
                        AND messages.batch_id IS NULL
                    """,
                    (
                        update_id,
                        chat_id,
                        int(message["message_id"]),
                        sender_id,
                        message.get("message_thread_id"),
                        int(message["date"]),
                        message.get("edit_date"),
                        kind,
                        body,
                        detect_content_type(message),
                        json.dumps(message, ensure_ascii=False, separators=(",", ":")),
                    ),
                )

        _advance_offset(connection, update_id)


def claim_batch(
    connection: sqlite3.Connection,
    max_batch_bytes: int = DEFAULT_MAX_BATCH_BYTES,
    *,
    through_id: int | None = None,
) -> tuple[str, list[sqlite3.Row]] | None:
    """Claim a context-safe slice, or resume the oldest failed batch.

    ``max_batch_bytes`` is a conservative proxy for model tokens. At least one
    row is claimed; the processor handles an individually oversized normalized
    input through context-safe partial summaries. ``through_id`` freezes a
    scheduled run at its startup high-water mark while collection continues.
    """

    if max_batch_bytes <= 0:
        raise ValueError("max_batch_bytes must be positive")

    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute(
            """
            SELECT batch_id
            FROM messages
            WHERE processed_at IS NULL
              AND batch_id IS NOT NULL
              AND (? IS NULL OR id <= ?)
            ORDER BY id
            LIMIT 1
            """,
            (through_id, through_id),
        ).fetchone()

        if existing:
            batch_id = str(existing["batch_id"])
        else:
            waiting = connection.execute(
                """
                SELECT id, body, content_type
                FROM messages
                WHERE processed_at IS NULL
                  AND batch_id IS NULL
                  AND (? IS NULL OR id <= ?)
                ORDER BY sent_at, id
                """,
                (through_id, through_id),
            ).fetchall()
            if not waiting:
                connection.commit()
                return None

            selected_ids: list[int] = []
            selected_bytes = 0
            for row in waiting:
                # Allow room for timestamps, labels, and JSON/prompt framing.
                row_bytes = len(str(row["body"]).encode("utf-8")) + 256
                if selected_ids and selected_bytes + row_bytes > max_batch_bytes:
                    break
                selected_ids.append(int(row["id"]))
                selected_bytes += row_bytes

            batch_id = uuid.uuid4().hex
            connection.executemany(
                """
                UPDATE messages
                SET batch_id = ?
                WHERE id = ?
                  AND processed_at IS NULL
                  AND batch_id IS NULL
                """,
                ((batch_id, row_id) for row_id in selected_ids),
            )

        claimed = connection.execute(
            """
            SELECT
                id,
                chat_id,
                message_id,
                thread_id,
                sent_at,
                kind,
                body,
                content_type,
                raw_json
            FROM messages
            WHERE batch_id = ?
              AND processed_at IS NULL
            ORDER BY sent_at, id
            """,
            (batch_id,),
        ).fetchall()
        connection.execute(
            """
            INSERT INTO batches (batch_id, created_at, message_count)
            VALUES (?, ?, ?)
            ON CONFLICT(batch_id) DO NOTHING
            """,
            (batch_id, int(time.time()), len(claimed)),
        )
        connection.commit()
        return batch_id, claimed
    except Exception:
        connection.rollback()
        raise


def rows_to_payload(
    rows: Iterable[Mapping[str, Any]],
    timezone: str | ZoneInfo,
) -> list[dict[str, Any]]:
    """Convert claimed rows to the stable input shape used by the agent."""

    local_timezone = ZoneInfo(timezone) if isinstance(timezone, str) else timezone
    return [
        {
            "id": row["id"],
            "type": row["kind"],
            "text": row["body"],
            "content_type": row["content_type"],
            "telegram": {
                "chat_id": row["chat_id"],
                "message_id": row["message_id"],
                "thread_id": row["thread_id"],
            },
            "sent_at": _local_isoformat(int(row["sent_at"]), local_timezone),
        }
        for row in rows
    ]


def _local_isoformat(timestamp: int, timezone: ZoneInfo) -> str:
    # Kept out of the comprehension to make timezone conversion easy to test.
    return datetime.fromtimestamp(timestamp, tz=timezone).isoformat()


def format_batch_for_agent(messages: Sequence[Mapping[str, Any]]) -> str:
    """Render normalized Telegram messages as a compact chronological dump."""

    sections: list[str] = []
    for message in messages:
        kind = str(message["type"]).upper()
        sent_at = str(message["sent_at"])
        content_type = str(message["content_type"])
        body = str(message["text"]).strip()
        if not body:
            body = f"[{content_type} attachment without text]"
        sections.append(f"[{kind}] {sent_at}\n{body}")
    return "\n\n".join(sections)


def mark_batch_processed(
    connection: sqlite3.Connection,
    batch_id: str,
    processed_at: int | None = None,
    *,
    summary: str | None = None,
    tags: Sequence[str] | None = None,
) -> int:
    """Persist the result and mark all rows complete in one transaction."""

    completion_time = int(time.time()) if processed_at is None else int(processed_at)
    with connection:
        cursor = connection.execute(
            """
            UPDATE messages
            SET processed_at = ?
            WHERE batch_id = ?
              AND processed_at IS NULL
            """,
            (completion_time, batch_id),
        )
        if cursor.rowcount:
            batch_cursor = connection.execute(
                """
                UPDATE batches
                SET summary = ?,
                    tags_json = ?,
                    processed_at = ?
                WHERE batch_id = ?
                """,
                (
                    summary,
                    json.dumps(list(tags or []), ensure_ascii=False, separators=(",", ":")),
                    completion_time,
                    batch_id,
                ),
            )
            if batch_cursor.rowcount != 1:
                raise RuntimeError(
                    f"batch metadata missing for {batch_id}; completion was rolled back"
                )
    return cursor.rowcount
