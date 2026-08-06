from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from telegram_collector import (
    CollectorConfig,
    TelegramAPIError,
    delete_webhook,
    get_updates,
    poll_once,
)
from telegram_store import get_next_offset


class FakeResponse:
    def __init__(
        self,
        payload: Any,
        *,
        status_code: int = 200,
        json_error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error
        self.text = "fake response body"

    def json(self) -> Any:
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)


def test_collector_config_from_env_parses_ids_paths_topics_and_defaults(
    telegram_environment: dict[str, str],
) -> None:
    config = CollectorConfig.from_env()

    assert config.bot_token == telegram_environment["TELEGRAM_BOT_TOKEN"]
    assert config.allowed_user_id == 300
    assert config.allowed_chat_id == 200
    assert config.db_path == telegram_environment["DB_PATH"]
    assert config.thought_thread_id == 12
    assert config.action_thread_id == 18
    assert config.api_root == "https://api.telegram.org"
    assert config.api_base == "https://api.telegram.org/bot123456:secret-token"
    assert config.poll_timeout == 50
    assert config.request_timeout == 65
    assert config.bot_token not in repr(config)


def test_collector_config_allows_topics_to_be_omitted(
    telegram_environment: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THOUGHT_THREAD_ID")
    monkeypatch.delenv("ACTION_THREAD_ID")

    config = CollectorConfig.from_env()

    assert config.thought_thread_id is None
    assert config.action_thread_id is None


@pytest.mark.parametrize("key", ["TELEGRAM_BOT_TOKEN", "ALLOWED_USER_ID", "ALLOWED_CHAT_ID"])
def test_collector_config_rejects_missing_required_values(
    telegram_environment: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    key: str,
) -> None:
    monkeypatch.delenv(key)

    with pytest.raises((KeyError, ValueError)):
        CollectorConfig.from_env()


def test_collector_config_rejects_non_numeric_ids(
    telegram_environment: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_USER_ID", "not-a-number")

    with pytest.raises(ValueError):
        CollectorConfig.from_env()


def test_get_updates_posts_expected_long_poll_request(
    telegram_environment: dict[str, str],
) -> None:
    config = CollectorConfig.from_env()
    expected = [{"update_id": 41, "message": {"message_id": 1}}]
    session = FakeSession(FakeResponse({"ok": True, "result": expected}))

    assert get_updates(session, config, offset=40) == expected

    url, request = session.calls[0]
    assert url == f"{config.api_base}/getUpdates"
    assert request["json"] == {
        "offset": 40,
        "limit": 100,
        "timeout": 50,
        "allowed_updates": ["message", "edited_message"],
    }
    assert request["timeout"] == 65


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse({"ok": False, "description": "Conflict: webhook active"}),
        FakeResponse({"ok": False}, status_code=502),
        FakeResponse(None, json_error=ValueError("not JSON")),
        FakeResponse({"ok": True, "result": {"not": "a list"}}),
    ],
)
def test_get_updates_normalizes_http_and_bot_api_failures(
    telegram_environment: dict[str, str],
    response: FakeResponse,
) -> None:
    config = CollectorConfig.from_env()

    with pytest.raises(TelegramAPIError):
        get_updates(FakeSession(response), config, offset=0)


def test_delete_webhook_preserves_pending_updates(
    telegram_environment: dict[str, str],
) -> None:
    config = CollectorConfig.from_env()
    session = FakeSession(FakeResponse({"ok": True, "result": True}))

    delete_webhook(session, config)

    url, request = session.calls[0]
    assert url == f"{config.api_base}/deleteWebhook"
    payload = request.get("json", request.get("data"))
    assert payload == {"drop_pending_updates": False}
    assert request["timeout"] == 65


def test_delete_webhook_raises_for_bot_api_failure(
    telegram_environment: dict[str, str],
) -> None:
    config = CollectorConfig.from_env()
    session = FakeSession(FakeResponse({"ok": False, "description": "bad request"}))

    with pytest.raises(TelegramAPIError, match="bad request"):
        delete_webhook(session, config)


def test_poll_once_stores_only_authorized_messages_and_advances_past_all_updates(
    database: sqlite3.Connection,
    telegram_environment: dict[str, str],
    make_update: Callable[..., dict[str, Any]],
) -> None:
    config = CollectorConfig.from_env()
    authorized_topic_message = make_update(
        update_id=100,
        message_id=10,
        thread_id=12,
        text="No prefix needed in a topic",
    )
    unauthorized_message = make_update(
        update_id=101,
        message_id=11,
        sender_id=999,
        text="a: ignored",
    )
    ignored_update = {"update_id": 102, "callback_query": {"id": "ignored"}}
    session = FakeSession(
        FakeResponse(
            {
                "ok": True,
                "result": [authorized_topic_message, unauthorized_message, ignored_update],
            }
        ),
        FakeResponse({"ok": True, "result": []}),
    )

    poll_once(session, database, config)

    rows = database.execute("SELECT kind, body FROM messages").fetchall()
    assert [tuple(row) for row in rows] == [("thought", "No prefix needed in a topic")]
    assert get_next_offset(database) == 103
    assert session.calls[0][1]["json"]["offset"] == 0

    poll_once(session, database, config)
    assert session.calls[1][1]["json"]["offset"] == 103


def test_poll_once_leaves_offset_unchanged_when_request_fails(
    database: sqlite3.Connection,
    telegram_environment: dict[str, str],
) -> None:
    config = CollectorConfig.from_env()
    session = FakeSession(FakeResponse({"ok": False, "description": "temporary failure"}))

    with pytest.raises(TelegramAPIError):
        poll_once(session, database, config)

    assert get_next_offset(database) == 0


def test_configured_database_path_can_be_passed_to_store_opening_code(
    telegram_environment: dict[str, str],
) -> None:
    config = CollectorConfig.from_env()

    assert Path(config.db_path).name == "messages.db"
