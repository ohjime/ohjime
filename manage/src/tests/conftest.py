from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from telegram_store import open_database


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = open_database(tmp_path / "state" / "messages.db")
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


@pytest.fixture
def make_update() -> Callable[..., dict[str, Any]]:
    def factory(
        *,
        update_id: int = 100,
        message_id: int = 10,
        chat_id: int = 200,
        sender_id: int = 300,
        sent_at: int = 1_786_063_332,
        text: str | None = "t: Test thought",
        caption: str | None = None,
        thread_id: int | None = None,
        edit_date: int | None = None,
        edited: bool = False,
        extra_message: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {
            "message_id": message_id,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": sender_id, "is_bot": False, "first_name": "Owner"},
            "date": sent_at,
        }
        if text is not None:
            message["text"] = text
        if caption is not None:
            message["caption"] = caption
        if thread_id is not None:
            message["message_thread_id"] = thread_id
        if edit_date is not None:
            message["edit_date"] = edit_date
        if extra_message:
            message.update(extra_message)
        key = "edited_message" if edited else "message"
        return {"update_id": update_id, key: message}

    return factory


@pytest.fixture
def telegram_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    values = {
        "TELEGRAM_BOT_TOKEN": "123456:secret-token",
        "ALLOWED_USER_ID": "300",
        "ALLOWED_CHAT_ID": "200",
        "DB_PATH": str(tmp_path / "messages.db"),
        "THOUGHT_THREAD_ID": "12",
        "ACTION_THREAD_ID": "18",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values
