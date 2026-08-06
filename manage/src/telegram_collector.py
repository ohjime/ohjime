"""Continuously collect private Telegram bot messages into SQLite."""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import requests
from dotenv import find_dotenv, load_dotenv

from telegram_store import StoredMessage, get_next_offset, open_database, store_update

DEFAULT_DB_PATH = "/var/lib/ohjime/messages.db"
MESSAGE_REACTIONS = {
    "thought": "✍",
    "action": "👍",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger(__name__)


class ConfigurationError(ValueError):
    """Raised when required collector configuration is missing or invalid."""


class TelegramAPIError(RuntimeError):
    """A safe-to-log Bot API failure that never includes the tokenized URL."""


def _safe_error(error: Exception) -> str:
    """Describe known API failures while redacting URL-bearing request errors."""

    if isinstance(error, TelegramAPIError):
        return f"{type(error).__name__}: {error}"
    return type(error).__name__


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"{name} must be set")
    return value


def _required_int(environ: Mapping[str, str], name: str) -> int:
    value = _required(environ, name)
    try:
        return int(value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a numeric Telegram ID") from error


def _optional_int(environ: Mapping[str, str], name: str) -> int | None:
    value = environ.get(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a numeric Telegram topic ID") from error


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    value = environ.get(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a positive integer") from error
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be a positive integer")
    return parsed


@dataclass(frozen=True)
class CollectorConfig:
    """Validated Telegram collector settings."""

    bot_token: str = field(repr=False)
    allowed_user_id: int
    allowed_chat_id: int
    db_path: str = DEFAULT_DB_PATH
    thought_thread_id: int | None = None
    action_thread_id: int | None = None
    api_root: str = "https://api.telegram.org"
    poll_timeout: int = 50
    request_timeout: int = 65

    @property
    def api_base(self) -> str:
        return f"{self.api_root.rstrip('/')}/bot{self.bot_token}"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> CollectorConfig:
        values = os.environ if environ is None else environ
        poll_timeout = _positive_int(values, "TELEGRAM_POLL_TIMEOUT", 50)
        request_timeout = _positive_int(values, "TELEGRAM_REQUEST_TIMEOUT", 65)
        if request_timeout <= poll_timeout:
            raise ConfigurationError(
                "TELEGRAM_REQUEST_TIMEOUT must be greater than TELEGRAM_POLL_TIMEOUT"
            )

        return cls(
            bot_token=_required(values, "TELEGRAM_BOT_TOKEN"),
            allowed_user_id=_required_int(values, "ALLOWED_USER_ID"),
            allowed_chat_id=_required_int(values, "ALLOWED_CHAT_ID"),
            db_path=values.get("DB_PATH", DEFAULT_DB_PATH).strip() or DEFAULT_DB_PATH,
            thought_thread_id=_optional_int(values, "THOUGHT_THREAD_ID"),
            action_thread_id=_optional_int(values, "ACTION_THREAD_ID"),
            api_root=values.get("TELEGRAM_API_ROOT", "https://api.telegram.org").strip()
            or "https://api.telegram.org",
            poll_timeout=poll_timeout,
            request_timeout=request_timeout,
        )


def _response_payload(response: requests.Response) -> dict[str, Any]:
    if response.status_code != 200:
        raise TelegramAPIError(f"Telegram returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as error:
        raise TelegramAPIError("Telegram returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise TelegramAPIError("Telegram returned an invalid response object")
    if not payload.get("ok"):
        description = payload.get("description")
        message = str(description) if description else "Unknown Bot API error"
        raise TelegramAPIError(message)
    return payload


def delete_webhook(session: requests.Session, config: CollectorConfig) -> None:
    """Switch the bot to long polling without dropping queued updates."""

    response = session.post(
        f"{config.api_base}/deleteWebhook",
        json={"drop_pending_updates": False},
        timeout=config.request_timeout,
    )
    _response_payload(response)


def get_updates(
    session: requests.Session,
    config: CollectorConfig,
    offset: int,
) -> list[dict[str, Any]]:
    """Long-poll Telegram for message and edited-message updates."""

    response = session.post(
        f"{config.api_base}/getUpdates",
        json={
            "offset": offset,
            "limit": 100,
            "timeout": config.poll_timeout,
            "allowed_updates": ["message", "edited_message"],
        },
        timeout=config.request_timeout,
    )
    payload = _response_payload(response)
    result = payload.get("result")
    if not isinstance(result, list):
        raise TelegramAPIError("Telegram response did not contain an update list")
    return result


def set_message_reaction(
    session: requests.Session,
    config: CollectorConfig,
    stored_message: StoredMessage,
) -> None:
    """Visually acknowledge a stored thought or action in Telegram."""

    emoji = MESSAGE_REACTIONS.get(stored_message.kind)
    if emoji is None:
        return
    response = session.post(
        f"{config.api_base}/setMessageReaction",
        json={
            "chat_id": stored_message.chat_id,
            "message_id": stored_message.message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
        },
        timeout=min(config.request_timeout, 5),
    )
    _response_payload(response)


def poll_once(
    session: requests.Session,
    connection: sqlite3.Connection,
    config: CollectorConfig,
) -> int:
    """Fetch and durably consume one page of updates; return its size."""

    updates = get_updates(session, config, get_next_offset(connection))
    stored_messages: list[StoredMessage] = []
    for update in updates:
        stored_message = store_update(
            connection,
            update,
            allowed_user_id=config.allowed_user_id,
            allowed_chat_id=config.allowed_chat_id,
            thought_thread_id=config.thought_thread_id,
            action_thread_id=config.action_thread_id,
        )
        if stored_message is not None:
            stored_messages.append(stored_message)

    # Store and acknowledge the complete Telegram page before attempting any
    # cosmetic API calls. Slow or unavailable reactions cannot delay storage.
    for stored_message in stored_messages:
        if stored_message.kind in MESSAGE_REACTIONS:
            try:
                set_message_reaction(session, config, stored_message)
            except Exception as error:  # noqa: BLE001 - reactions are cosmetic only
                LOGGER.warning(
                    "Stored %s message %s, but its reaction failed: %s",
                    stored_message.kind,
                    stored_message.message_id,
                    _safe_error(error),
                )
    return len(updates)


def main() -> int:
    load_dotenv(find_dotenv())
    try:
        config = CollectorConfig.from_env()
    except ConfigurationError as error:
        LOGGER.error("Collector configuration error: %s", error)
        return 2

    connection = open_database(config.db_path)
    session = requests.Session()

    try:
        # getUpdates and webhooks are mutually exclusive.  This is idempotent
        # and explicitly preserves any updates already queued by Telegram.
        delete_webhook(session, config)
        LOGGER.info("Telegram collector started; database=%s", config.db_path)

        while True:
            try:
                poll_once(session, connection, config)
            except KeyboardInterrupt:
                return 0
            except Exception as error:  # noqa: BLE001 - daemon retries all transient failures
                # requests exceptions include the request URL, which embeds the
                # bot token.  Log only the type here to avoid leaking it.
                LOGGER.error("Collector error: %s", _safe_error(error))
                time.sleep(5)
    except KeyboardInterrupt:
        return 0
    except Exception as error:  # noqa: BLE001 - convert startup failures to service status
        LOGGER.error("Collector startup error: %s", _safe_error(error))
        return 1
    finally:
        session.close()
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
