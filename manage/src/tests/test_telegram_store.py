from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from telegram_store import (
    claim_batch,
    classify_message,
    detect_content_type,
    format_batch_for_agent,
    get_next_offset,
    get_pending_high_watermark,
    mark_batch_processed,
    open_database,
    rows_to_payload,
    store_update,
)

ALLOWED_CHAT_ID = 200
ALLOWED_USER_ID = 300


def store(
    connection: sqlite3.Connection,
    update: dict[str, Any],
    *,
    thought_thread_id: int | None = None,
    action_thread_id: int | None = None,
) -> None:
    store_update(
        connection,
        update,
        allowed_user_id=ALLOWED_USER_ID,
        allowed_chat_id=ALLOWED_CHAT_ID,
        thought_thread_id=thought_thread_id,
        action_thread_id=action_thread_id,
    )


@pytest.mark.parametrize(
    ("original", "kind", "body"),
    [
        ("t: a short thought", "thought", "a short thought"),
        (" Thought :  a longer thought  ", "thought", "a longer thought"),
        ("A: ship it", "action", "ship it"),
        ("action: implement grouping", "action", "implement grouping"),
        ("/thought consider SQLite", "thought", "consider SQLite"),
        ("/t@ThoughtBot consider topics", "thought", "consider topics"),
        ("/action\nfirst line\nsecond line", "action", "first line\nsecond line"),
        (" /a@ThoughtBot   deploy it ", "action", "deploy it"),
        ("/thought", "thought", ""),
        ("unclassified note", "unknown", "unclassified note"),
    ],
)
def test_classify_message_text_variants(original: str, kind: str, body: str) -> None:
    assert classify_message({"text": original}) == (kind, body)


def test_classify_message_uses_caption_when_text_is_absent() -> None:
    assert classify_message({"caption": "a: inspect the diagram"}) == (
        "action",
        "inspect the diagram",
    )


def test_classify_message_prefers_configured_topic_over_prefix() -> None:
    message = {"message_thread_id": 12, "text": "a: this remains topic text"}

    assert classify_message(message, thought_thread_id=12, action_thread_id=18) == (
        "thought",
        "a: this remains topic text",
    )


def test_classify_message_action_topic_without_prefix() -> None:
    message = {"message_thread_id": 18, "text": "Implement the collector"}

    assert classify_message(message, thought_thread_id=12, action_thread_id=18) == (
        "action",
        "Implement the collector",
    )


def test_classify_message_with_no_text_or_caption_is_unknown() -> None:
    assert classify_message({"photo": [{"file_id": "photo"}]}) == ("unknown", "")


@pytest.mark.parametrize(
    "content_type",
    [
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
    ],
)
def test_detect_content_type_recognizes_telegram_payloads(content_type: str) -> None:
    assert detect_content_type({content_type: object()}) == content_type


def test_detect_content_type_falls_back_to_other() -> None:
    assert detect_content_type({"dice": {"value": 6}}) == "other"


def test_open_database_creates_parent_schema_index_and_wal(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "messages.db"

    connection = open_database(path)
    try:
        objects = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        assert ("table", "bot_state") in objects
        assert ("table", "messages") in objects
        assert ("table", "batches") in objects
        assert ("index", "messages_unprocessed") in objects
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert get_next_offset(connection) == 0
    finally:
        connection.close()


def test_open_database_is_idempotent_and_preserves_state(tmp_path: Path) -> None:
    path = tmp_path / "messages.db"
    first = open_database(path)
    first.execute("INSERT INTO bot_state (key, value) VALUES ('next_offset', '42')")
    first.commit()
    first.close()

    second = open_database(path)
    try:
        assert get_next_offset(second) == 42
    finally:
        second.close()


def test_store_update_persists_authorized_message_and_offset(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    update = make_update(thread_id=12)
    message = update["message"]

    store(database, update, thought_thread_id=12, action_thread_id=18)

    row = database.execute("SELECT * FROM messages").fetchone()
    assert row is not None
    assert row["update_id"] == 100
    assert row["chat_id"] == ALLOWED_CHAT_ID
    assert row["message_id"] == 10
    assert row["sender_id"] == ALLOWED_USER_ID
    assert row["thread_id"] == 12
    assert row["sent_at"] == 1_786_063_332
    assert row["edited_at"] is None
    assert row["kind"] == "thought"
    assert row["body"] == "t: Test thought"
    assert row["content_type"] == "text"
    assert json.loads(row["raw_json"]) == message
    assert row["batch_id"] is None
    assert row["processed_at"] is None
    assert get_next_offset(database) == 101


@pytest.mark.parametrize(
    ("chat_id", "sender_id"),
    [(999, ALLOWED_USER_ID), (ALLOWED_CHAT_ID, 999), (999, 999)],
)
def test_store_update_ignores_unauthorized_message_but_advances_offset(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
    chat_id: int,
    sender_id: int,
) -> None:
    store(database, make_update(update_id=130, chat_id=chat_id, sender_id=sender_id))

    assert database.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert get_next_offset(database) == 131


def test_store_update_ignores_non_message_update_but_advances_offset(
    database: sqlite3.Connection,
) -> None:
    store(database, {"update_id": 140, "callback_query": {"id": "ignored"}})

    assert database.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert get_next_offset(database) == 141


def test_store_update_rolls_back_message_when_offset_write_fails(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    database.executescript(
        """
        CREATE TRIGGER reject_offset_insert
        BEFORE INSERT ON bot_state
        BEGIN
            SELECT RAISE(ABORT, 'simulated offset failure');
        END;
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="simulated offset failure"):
        store(database, make_update())

    assert database.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert get_next_offset(database) == 0


def test_replayed_older_update_cannot_move_offset_backwards(
    database: sqlite3.Connection,
) -> None:
    store(database, {"update_id": 200, "callback_query": {"id": "newer"}})
    store(database, {"update_id": 150, "callback_query": {"id": "replayed"}})

    assert get_next_offset(database) == 201


def test_duplicate_delivery_is_idempotent(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    update = make_update()

    store(database, update)
    store(database, update)

    assert database.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    assert get_next_offset(database) == 101


def test_edit_updates_an_unclaimed_message_in_place(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update(update_id=100, text="t: original"))
    edited = make_update(
        update_id=101,
        text="a: revised",
        edit_date=1_786_063_400,
        edited=True,
    )

    store(database, edited)

    row = database.execute("SELECT * FROM messages").fetchone()
    assert database.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    assert row["update_id"] == 101
    assert row["kind"] == "action"
    assert row["body"] == "revised"
    assert row["edited_at"] == 1_786_063_400
    assert json.loads(row["raw_json"]) == edited["edited_message"]
    assert get_next_offset(database) == 102


def test_edit_does_not_change_a_claimed_retry_batch(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update(update_id=100, text="t: stable retry text"))
    batch_id, _ = claim_batch(database)

    store(
        database,
        make_update(
            update_id=101,
            text="a: late edit",
            edit_date=1_786_063_400,
            edited=True,
        ),
    )

    row = database.execute("SELECT * FROM messages").fetchone()
    assert row["batch_id"] == batch_id
    assert row["update_id"] == 100
    assert row["kind"] == "thought"
    assert row["body"] == "stable retry text"
    assert row["edited_at"] is None
    assert get_next_offset(database) == 102


def test_edit_does_not_change_a_processed_message(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update(update_id=100, text="t: completed text"))
    batch_id, _ = claim_batch(database)
    mark_batch_processed(database, batch_id, processed_at=1_786_064_000)

    store(
        database,
        make_update(
            update_id=102,
            text="a: too late",
            edit_date=1_786_064_100,
            edited=True,
        ),
    )

    row = database.execute("SELECT * FROM messages").fetchone()
    assert row["kind"] == "thought"
    assert row["body"] == "completed text"
    assert row["processed_at"] == 1_786_064_000
    assert get_next_offset(database) == 103


def test_claim_batch_returns_none_when_no_messages_exist(
    database: sqlite3.Connection,
) -> None:
    assert claim_batch(database) is None


def test_pending_high_watermark_excludes_rows_inserted_later(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update(update_id=100, message_id=10))
    through_id = get_pending_high_watermark(database)
    store(database, make_update(update_id=101, message_id=11))

    _, rows = claim_batch(database, through_id=through_id)

    assert [row["message_id"] for row in rows] == [10]
    later = database.execute(
        "SELECT batch_id FROM messages WHERE message_id = 11"
    ).fetchone()
    assert later["batch_id"] is None


def test_claim_batch_orders_rows_and_assigns_one_stable_id(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update(update_id=100, message_id=10, sent_at=20, text="t: later"))
    store(database, make_update(update_id=101, message_id=11, sent_at=10, text="a: earlier"))
    store(database, make_update(update_id=102, message_id=12, sent_at=20, text="t: tied"))

    batch_id, rows = claim_batch(database)

    assert batch_id
    assert [row["message_id"] for row in rows] == [11, 10, 12]
    assert {row["batch_id"] for row in database.execute("SELECT batch_id FROM messages")} == {
        batch_id
    }


def test_claim_batch_rolls_back_every_assignment_when_one_update_fails(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update(update_id=100, message_id=10, sent_at=10))
    store(database, make_update(update_id=101, message_id=11, sent_at=20))
    database.executescript(
        """
        CREATE TRIGGER reject_second_batch_assignment
        BEFORE UPDATE OF batch_id ON messages
        WHEN OLD.message_id = 11
        BEGIN
            SELECT RAISE(ABORT, 'simulated claim failure');
        END;
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="simulated claim failure"):
        claim_batch(database)

    rows = database.execute(
        "SELECT batch_id, processed_at FROM messages ORDER BY message_id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [(None, None), (None, None)]

    database.execute("DROP TRIGGER reject_second_batch_assignment")
    database.commit()
    batch_id, claimed = claim_batch(database)
    assert batch_id
    assert [row["message_id"] for row in claimed] == [10, 11]


def test_failed_batch_is_resumed_before_messages_that_arrive_later(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update(update_id=100, message_id=10, text="t: first"))
    first_batch_id, first_rows = claim_batch(database)
    store(database, make_update(update_id=101, message_id=11, text="a: arrived later"))

    retry_batch_id, retry_rows = claim_batch(database)

    assert retry_batch_id == first_batch_id
    assert [row["id"] for row in retry_rows] == [row["id"] for row in first_rows]
    later = database.execute("SELECT batch_id FROM messages WHERE message_id = 11").fetchone()
    assert later["batch_id"] is None

    mark_batch_processed(database, first_batch_id, processed_at=1_786_064_000)
    second_batch_id, second_rows = claim_batch(database)
    assert second_batch_id != first_batch_id
    assert [row["message_id"] for row in second_rows] == [11]


def test_mark_batch_processed_only_marks_the_requested_batch(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update(update_id=100, message_id=10))
    batch_id, _ = claim_batch(database)
    store(database, make_update(update_id=101, message_id=11))

    mark_batch_processed(database, batch_id, processed_at=1_786_064_000)

    completed = database.execute(
        "SELECT processed_at FROM messages WHERE message_id = 10"
    ).fetchone()
    pending = database.execute(
        "SELECT processed_at, batch_id FROM messages WHERE message_id = 11"
    ).fetchone()
    assert completed["processed_at"] == 1_786_064_000
    assert pending["processed_at"] is None
    assert pending["batch_id"] is None


def test_claim_batch_respects_context_budget_and_leaves_overflow_waiting(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update(update_id=100, message_id=10, text="t: first"))
    store(database, make_update(update_id=101, message_id=11, text="a: second"))

    batch_id, rows = claim_batch(database, max_batch_bytes=300)

    assert [row["message_id"] for row in rows] == [10]
    waiting = database.execute(
        "SELECT batch_id FROM messages WHERE message_id = 11"
    ).fetchone()
    assert waiting["batch_id"] is None
    mark_batch_processed(database, batch_id, processed_at=1_786_064_000)
    _, next_rows = claim_batch(database, max_batch_bytes=300)
    assert [row["message_id"] for row in next_rows] == [11]


def test_mark_batch_processed_persists_summary_and_tags_atomically(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update())
    batch_id, _ = claim_batch(database)

    mark_batch_processed(
        database,
        batch_id,
        processed_at=1_786_064_000,
        summary="Persisted summary",
        tags=["sqlite", "telegram"],
    )

    result = database.execute(
        "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
    ).fetchone()
    assert result["summary"] == "Persisted summary"
    assert json.loads(result["tags_json"]) == ["sqlite", "telegram"]
    assert result["processed_at"] == 1_786_064_000


def test_mark_batch_processed_rolls_back_if_batch_metadata_is_missing(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update())
    batch_id, _ = claim_batch(database)
    database.execute("DELETE FROM batches WHERE batch_id = ?", (batch_id,))
    database.commit()

    with pytest.raises(RuntimeError, match="batch metadata missing"):
        mark_batch_processed(
            database,
            batch_id,
            processed_at=1_786_064_000,
            summary="Must not be lost",
            tags=["atomic"],
        )

    row = database.execute(
        "SELECT processed_at FROM messages WHERE batch_id = ?", (batch_id,)
    ).fetchone()
    assert row["processed_at"] is None


def test_mark_batch_processed_rolls_back_all_rows_when_one_update_fails(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(database, make_update(update_id=100, message_id=10))
    store(database, make_update(update_id=101, message_id=11))
    batch_id, _ = claim_batch(database)
    database.executescript(
        """
        CREATE TRIGGER reject_second_completion
        BEFORE UPDATE OF processed_at ON messages
        WHEN OLD.message_id = 11
        BEGIN
            SELECT RAISE(ABORT, 'simulated completion failure');
        END;
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="simulated completion failure"):
        mark_batch_processed(database, batch_id, processed_at=1_786_064_000)

    rows = database.execute(
        "SELECT batch_id, processed_at FROM messages ORDER BY message_id"
    ).fetchall()
    assert {row["batch_id"] for row in rows} == {batch_id}
    assert all(row["processed_at"] is None for row in rows)

    database.execute("DROP TRIGGER reject_second_completion")
    database.commit()
    assert mark_batch_processed(database, batch_id, processed_at=1_786_064_001) == 2


def test_rows_to_payload_maps_database_fields_and_localizes_timestamp(
    database: sqlite3.Connection,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    store(
        database,
        make_update(
            thread_id=18,
            text=None,
            caption="caption without a prefix",
            extra_message={"photo": [{"file_id": "photo-1"}]},
        ),
        thought_thread_id=12,
        action_thread_id=18,
    )
    batch_id, rows = claim_batch(database)

    payload = rows_to_payload(rows, ZoneInfo("America/Edmonton"))

    assert payload == [
        {
            "id": rows[0]["id"],
            "type": "action",
            "text": "caption without a prefix",
            "content_type": "photo",
            "telegram": {
                "chat_id": ALLOWED_CHAT_ID,
                "message_id": 10,
                "thread_id": 18,
            },
            "sent_at": "2026-08-06T18:42:12-06:00",
        }
    ]
    assert batch_id


def test_format_batch_for_agent_preserves_labels_text_and_order() -> None:
    messages = [
        {
            "type": "thought",
            "text": "Consider grouping related notes.",
            "content_type": "text",
            "sent_at": "2026-08-06T18:42:12-06:00",
        },
        {
            "type": "action",
            "text": "Implement grouping by project.",
            "content_type": "text",
            "sent_at": "2026-08-06T18:45:00-06:00",
        },
    ]

    formatted = format_batch_for_agent(messages)
    lowered = formatted.lower()

    assert formatted.index(messages[0]["text"]) < formatted.index(messages[1]["text"])
    assert lowered.count("thought") >= 1
    assert lowered.count("action") >= 1
    assert formatted.count(messages[0]["text"]) == 1
    assert formatted.count(messages[1]["text"]) == 1


def test_format_empty_batch_for_agent_is_empty() -> None:
    assert format_batch_for_agent([]) == ""


def test_format_batch_describes_an_attachment_without_text() -> None:
    formatted = format_batch_for_agent(
        [
            {
                "type": "unknown",
                "text": "",
                "content_type": "voice",
                "sent_at": "2026-08-06T18:45:00-06:00",
            }
        ]
    )

    assert "[voice attachment without text]" in formatted
