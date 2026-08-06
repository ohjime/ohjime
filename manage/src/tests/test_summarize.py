from __future__ import annotations

import asyncio
import sqlite3
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

import summarize
from telegram_store import open_database, store_update

ALLOWED_CHAT_ID = 200
ALLOWED_USER_ID = 300


def _store_updates(path: Path, updates: Sequence[dict[str, Any]]) -> None:
    connection = open_database(path)
    try:
        for update in updates:
            store_update(
                connection,
                update,
                allowed_user_id=ALLOWED_USER_ID,
                allowed_chat_id=ALLOWED_CHAT_ID,
            )
    finally:
        connection.close()


def _read_rows(path: Path) -> list[sqlite3.Row]:
    connection = open_database(path)
    try:
        return connection.execute("SELECT * FROM messages ORDER BY message_id").fetchall()
    finally:
        connection.close()


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    database_path: Path,
    *extra_arguments: str,
) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize.py",
            "--db-path",
            str(database_path),
            "--timezone",
            "America/Edmonton",
            "--max-batch-bytes",
            "12000",
            *extra_arguments,
        ],
    )
    return asyncio.run(summarize.main())


def test_main_with_no_work_returns_success_without_calling_processor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "messages.db"

    async def unexpected_processor(
        messages: list[dict[str, Any]],
        *,
        batch_id: str,
        max_input_bytes: int,
    ) -> tuple[str, list[str]]:
        pytest.fail(
            f"processor called for empty batch {batch_id}/{max_input_bytes}: {messages}"
        )

    monkeypatch.setattr(summarize, "process_messages", unexpected_processor)

    assert _run_main(monkeypatch, database_path) == 0
    assert "No unprocessed Telegram messages" in capsys.readouterr().out
    assert _read_rows(database_path) == []


def test_main_rejects_invalid_timezone_before_opening_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "should-not-exist.db"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize.py",
            "--db-path",
            str(database_path),
            "--timezone",
            "Not/A_Real_Timezone",
            "--max-batch-bytes",
            "12000",
        ],
    )

    assert asyncio.run(summarize.main()) == 2
    assert "unknown timezone" in capsys.readouterr().err
    assert not database_path.exists()


def test_dry_run_keeps_batch_unprocessed_and_stable_for_the_next_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    database_path = tmp_path / "messages.db"
    _store_updates(database_path, [make_update(text="t: preview this")])
    calls: list[tuple[str, list[dict[str, Any]]]] = []

    async def fake_processor(
        messages: list[dict[str, Any]],
        *,
        batch_id: str,
        max_input_bytes: int,
    ) -> tuple[str, list[str]]:
        assert max_input_bytes == 12000
        calls.append((batch_id, messages))
        return "Dry-run summary", ["preview"]

    monkeypatch.setattr(summarize, "process_messages", fake_processor)

    assert _run_main(monkeypatch, database_path, "--dry-run") == 0
    first_row = _read_rows(database_path)[0]
    assert first_row["batch_id"] == calls[0][0]
    assert first_row["processed_at"] is None

    assert _run_main(monkeypatch, database_path, "--dry-run") == 0
    second_row = _read_rows(database_path)[0]
    assert calls[1] == calls[0]
    assert second_row["batch_id"] == first_row["batch_id"]
    assert second_row["processed_at"] is None


def test_empty_model_response_fails_and_leaves_batch_queued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_update: Callable[..., dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "messages.db"
    _store_updates(database_path, [make_update(text="t: do not lose this")])
    prompts: list[str] = []

    async def empty_summary(notes: str) -> str:
        prompts.append(notes)
        # run_summary strips the model's chunks before returning this boundary.
        return ""

    monkeypatch.setattr(summarize, "run_summary", empty_summary)

    assert _run_main(monkeypatch, database_path) == 1

    row = _read_rows(database_path)[0]
    assert row["batch_id"]
    assert row["processed_at"] is None
    assert "do not lose this" in prompts[0]
    assert "RuntimeError" in capsys.readouterr().err


@pytest.mark.parametrize(
    "raw",
    ["not json", "{}", '{"summary":"","tags":[]}', '{"summary":"ok","tags":{}}'],
)
def test_parse_model_output_rejects_unusable_results(raw: str) -> None:
    with pytest.raises(summarize.ModelOutputError):
        summarize.parse_model_output(raw)


def test_parse_model_output_accepts_a_valid_object_with_surrounding_text() -> None:
    assert summarize.parse_model_output(
        'result: {"summary":"A useful summary","tags":["one","two"]}'
    ) == ("A useful summary", ["one", "two"])


def test_split_model_input_preserves_unicode_within_byte_limit() -> None:
    original = "é" * 10

    chunks = summarize.split_model_input(original, max_bytes=7)

    assert "".join(chunks) == original
    assert all(len(chunk.encode("utf-8")) <= 7 for chunk in chunks)


def test_oversized_input_uses_partial_summaries_then_synthesizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies = iter(
        [
            '{"summary":"First partial","tags":["first"]}',
            '{"summary":"Second partial","tags":["second"]}',
            '{"summary":"Combined","tags":["combined"]}',
        ]
    )
    prompts: list[str] = []

    async def fake_run_summary(notes: str) -> str:
        prompts.append(notes)
        return next(replies)

    monkeypatch.setattr(summarize, "run_summary", fake_run_summary)
    messages = [
        {
            "type": "thought",
            "text": "x" * (summarize.DEFAULT_MAX_BATCH_BYTES + 1),
            "content_type": "text",
            "sent_at": "2026-08-06T18:42:12-06:00",
        }
    ]

    result = asyncio.run(summarize.process_messages(messages, batch_id="oversized"))

    assert result == ("Combined", ["combined"])
    assert len(prompts) == 3
    assert "First partial" in prompts[-1]
    assert "Second partial" in prompts[-1]


def test_partial_synthesis_fails_instead_of_looping_when_results_do_not_shrink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized_summary = "x" * summarize.MODEL_INPUT_BYTES

    async def large_run_summary(notes: str) -> str:
        del notes
        return '{"summary":"' + oversized_summary + '","tags":[]}'

    monkeypatch.setattr(summarize, "run_summary", large_run_summary)
    messages = [
        {
            "type": "thought",
            "text": "y" * (summarize.DEFAULT_MAX_BATCH_BYTES + 1),
            "content_type": "text",
            "sent_at": "2026-08-06T18:42:12-06:00",
        }
    ]

    with pytest.raises(summarize.ModelOutputError, match="did not reduce"):
        asyncio.run(summarize.process_messages(messages, batch_id="non-reducing"))


def test_failure_retries_stable_batch_then_drains_deferred_arrival(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    database_path = tmp_path / "messages.db"
    _store_updates(
        database_path,
        [
            make_update(update_id=100, message_id=10, sent_at=100, text="t: first"),
            make_update(update_id=101, message_id=11, sent_at=200, text="a: second"),
        ],
    )
    calls: list[tuple[str, list[dict[str, Any]]]] = []

    async def flaky_processor(
        messages: list[dict[str, Any]],
        *,
        batch_id: str,
        max_input_bytes: int,
    ) -> tuple[str, list[str]]:
        assert max_input_bytes == 12000
        calls.append((batch_id, messages))
        if len(calls) == 1:
            raise RuntimeError("temporary model failure")
        return "Recovered summary", ["recovered"]

    monkeypatch.setattr(summarize, "process_messages", flaky_processor)

    assert _run_main(monkeypatch, database_path) == 1
    failed_rows = _read_rows(database_path)
    failed_batch_id = calls[0][0]
    assert {row["batch_id"] for row in failed_rows} == {failed_batch_id}
    assert all(row["processed_at"] is None for row in failed_rows)

    _store_updates(
        database_path,
        [make_update(update_id=102, message_id=12, sent_at=300, text="t: arrived later")],
    )

    assert _run_main(monkeypatch, database_path) == 0
    assert calls[1] == calls[0]
    assert calls[2][0] != failed_batch_id
    assert [message["telegram"]["message_id"] for message in calls[2][1]] == [12]
    assert all(row["processed_at"] is not None for row in _read_rows(database_path))


def test_main_drains_multiple_context_sized_batches_in_one_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    database_path = tmp_path / "messages.db"
    _store_updates(
        database_path,
        [
            make_update(update_id=100, message_id=10, text="t: first"),
            make_update(update_id=101, message_id=11, text="a: second"),
        ],
    )
    calls: list[list[int]] = []

    async def fake_processor(
        messages: list[dict[str, Any]],
        *,
        batch_id: str,
        max_input_bytes: int,
    ) -> tuple[str, list[str]]:
        assert max_input_bytes == 512
        del batch_id
        calls.append([message["telegram"]["message_id"] for message in messages])
        return "Chunk summary", ["chunk"]

    monkeypatch.setattr(summarize, "process_messages", fake_processor)

    assert _run_main(
        monkeypatch,
        database_path,
        "--max-batch-bytes",
        "512",
    ) == 0
    assert calls == [[10], [11]]
    assert all(row["processed_at"] is not None for row in _read_rows(database_path))


def test_main_leaves_messages_arriving_after_start_for_the_next_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_update: Callable[..., dict[str, Any]],
) -> None:
    database_path = tmp_path / "messages.db"
    _store_updates(database_path, [make_update(update_id=100, message_id=10)])
    calls = 0

    async def processor_with_arrival(
        messages: list[dict[str, Any]],
        *,
        batch_id: str,
        max_input_bytes: int,
    ) -> tuple[str, list[str]]:
        nonlocal calls
        assert max_input_bytes == 12000
        del messages, batch_id
        calls += 1
        if calls == 1:
            _store_updates(
                database_path,
                [make_update(update_id=101, message_id=11, text="t: after cutoff")],
            )
        return "Snapshot summary", ["snapshot"]

    monkeypatch.setattr(summarize, "process_messages", processor_with_arrival)

    assert _run_main(monkeypatch, database_path) == 0
    rows = {row["message_id"]: row for row in _read_rows(database_path)}
    assert rows[10]["processed_at"] is not None
    assert rows[11]["batch_id"] is None
    assert rows[11]["processed_at"] is None
