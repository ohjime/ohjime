from __future__ import annotations

import sqlite3

from configure_telegram_env import (
    matching_setup_message,
    reset_polling_offset,
    set_environment_values,
    terminal_safe,
)


def test_terminal_safe_removes_control_characters() -> None:
    assert terminal_safe("owner\x1b[31m\nname") == "owner [31m name"


def test_matching_setup_message_ignores_newer_unrelated_updates() -> None:
    updates = [
        {"update_id": 3, "callback_query": {"id": "ignored"}},
        {
            "update_id": 4,
            "message": {
                "from": {"id": 10},
                "chat": {"id": 20},
                "text": "t: setup abc123",
            },
        },
        {
            "update_id": 5,
            "edited_message": {
                "from": {"id": 11},
                "chat": {"id": -30},
                "text": "newer",
            },
        },
    ]

    update_id, message = matching_setup_message(updates, "t: setup abc123") or (None, None)

    assert update_id == 4
    assert message is not None
    assert message["from"]["id"] == 10
    assert message["chat"]["id"] == 20


def test_set_environment_values_replaces_secrets_and_preserves_other_settings() -> None:
    original = """\
TELEGRAM_BOT_TOKEN=replace_with_real_token
ALLOWED_USER_ID=replace_with_numeric_user_id
ALLOWED_CHAT_ID=replace_with_numeric_chat_id
DB_PATH=/custom/messages.db
LOCAL_TIMEZONE=America/Edmonton
"""

    updated = set_environment_values(
        original,
        {
            "TELEGRAM_BOT_TOKEN": "123456:secret",
            "ALLOWED_USER_ID": "111",
            "ALLOWED_CHAT_ID": "-222",
        },
    )

    assert "TELEGRAM_BOT_TOKEN=123456:secret" in updated
    assert "ALLOWED_USER_ID=111" in updated
    assert "ALLOWED_CHAT_ID=-222" in updated
    assert "DB_PATH=/custom/messages.db" in updated
    assert "LOCAL_TIMEZONE=America/Edmonton" in updated


def test_reset_polling_offset_preserves_other_database_state(tmp_path) -> None:
    database_path = tmp_path / "messages.db"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE bot_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO bot_state VALUES ('next_offset', '900000')")
    connection.execute("INSERT INTO bot_state VALUES ('unrelated', 'keep-me')")
    connection.commit()
    connection.close()

    assert reset_polling_offset(database_path) is True

    connection = sqlite3.connect(database_path)
    rows = dict(connection.execute("SELECT key, value FROM bot_state"))
    connection.close()
    assert rows == {"unrelated": "keep-me"}
