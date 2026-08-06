"""Interactively create the protected Ubuntu Telegram environment file."""

from __future__ import annotations

import getpass
import os
import re
import secrets
import sqlite3
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import requests

DEFAULT_CONFIG_PATH = Path("/etc/ohjime/telegram.env")
DEFAULT_DB_PATH = Path("/var/lib/ohjime/messages.db")
TEMPLATE_PATH = Path(__file__).resolve().parent / "deploy" / "telegram.env.example"
TOKEN_PATTERN = re.compile(r"^[0-9]+:[A-Za-z0-9_-]+$")
COLLECTOR_UNIT = "ohjime-telegram-collector.service"


class TelegramSetupError(RuntimeError):
    """A configuration failure safe to show without exposing the bot token."""


def terminal_safe(value: object, limit: int = 160) -> str:
    """Remove terminal control characters from Bot API supplied text."""

    cleaned = "".join(character if character.isprintable() else " " for character in str(value))
    return cleaned[:limit]


def stop_collector_if_active() -> bool:
    """Stop a competing long poller, returning whether it should be restored."""

    status = subprocess.run(
        ["systemctl", "is-active", "--quiet", COLLECTOR_UNIT],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if status.returncode != 0:
        return False
    try:
        subprocess.run(
            ["systemctl", "stop", COLLECTOR_UNIT],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as error:
        raise TelegramSetupError("could not stop the active Telegram collector") from error
    print("Temporarily stopped the active Telegram collector.")
    return True


def restore_collector() -> None:
    """Best-effort restoration after cancelled or failed reconfiguration."""

    result = subprocess.run(
        ["systemctl", "start", COLLECTOR_UNIT],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode == 0:
        print("Restored the previous Telegram collector configuration.")
    else:
        print(f"warning: could not restore {COLLECTOR_UNIT}; inspect it with systemctl status")


def telegram_call(
    session: requests.Session,
    token: str,
    method: str,
    payload: Mapping[str, Any] | None = None,
    *,
    timeout: int = 25,
) -> Any:
    """Call one Bot API method while keeping tokenized URLs out of errors."""

    try:
        response = session.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=dict(payload or {}),
            timeout=timeout,
        )
    except requests.RequestException as error:
        raise TelegramSetupError(
            f"Telegram request failed ({type(error).__name__})"
        ) from error

    if response.status_code != 200:
        raise TelegramSetupError(f"Telegram returned HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as error:
        raise TelegramSetupError("Telegram returned invalid JSON") from error
    if not isinstance(body, dict) or not body.get("ok"):
        description = body.get("description") if isinstance(body, dict) else None
        detail = str(description) if description else "Bot API rejected the request"
        raise TelegramSetupError(detail)
    return body.get("result")


def matching_setup_message(
    updates: Sequence[Mapping[str, Any]],
    expected_text: str,
) -> tuple[int, Mapping[str, Any]] | None:
    """Return the newest usable message whose text exactly matches setup text."""

    candidates: list[tuple[int, Mapping[str, Any]]] = []
    for update in updates:
        message = update.get("message") or update.get("edited_message")
        sender = message.get("from") if isinstance(message, Mapping) else None
        chat = message.get("chat") if isinstance(message, Mapping) else None
        message_text = (
            str(message.get("text") or message.get("caption") or "").strip()
            if isinstance(message, Mapping)
            else ""
        )
        if (
            isinstance(sender, Mapping)
            and isinstance(chat, Mapping)
            and sender.get("id") is not None
            and chat.get("id") is not None
            and message_text == expected_text
        ):
            candidates.append((int(update.get("update_id", 0)), message))
    return max(candidates, key=lambda item: item[0]) if candidates else None


def wait_for_setup_message(
    session: requests.Session,
    token: str,
    expected_text: str,
    *,
    wait_seconds: int = 120,
) -> tuple[int, Mapping[str, Any]]:
    """Page through queued updates until the one-time setup message arrives.

    Advancing the offset acknowledges older pre-configuration updates. This is
    intentional during setup and prevents an old message from authorizing the
    wrong sender or chat.
    """

    offset = 0
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        result = telegram_call(
            session,
            token,
            "getUpdates",
            {
                "offset": offset,
                "limit": 100,
                "timeout": 10,
                "allowed_updates": ["message", "edited_message"],
            },
            timeout=20,
        )
        updates = result if isinstance(result, list) else []
        selected = matching_setup_message(updates, expected_text)
        if selected is not None:
            return selected

        update_ids = [
            int(update["update_id"])
            for update in updates
            if isinstance(update, Mapping) and update.get("update_id") is not None
        ]
        if update_ids:
            offset = max(offset, max(update_ids) + 1)

    raise TelegramSetupError("timed out waiting for the one-time setup message")


def set_environment_values(text: str, values: Mapping[str, str]) -> str:
    """Replace or append simple systemd EnvironmentFile assignments."""

    updated = text
    for key, value in values.items():
        pattern = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=.*$", re.MULTILINE)
        assignment = f"{key}={value}"
        if pattern.search(updated):
            updated = pattern.sub(assignment, updated)
        else:
            updated = updated.rstrip("\n") + f"\n{assignment}\n"
    return updated if updated.endswith("\n") else updated + "\n"


def configured_database_path(config_path: Path) -> Path:
    """Read the preserved DB_PATH setting without interpreting shell syntax."""

    source = (
        config_path.read_text(encoding="utf-8")
        if config_path.exists()
        else TEMPLATE_PATH.read_text(encoding="utf-8")
    )
    matches = re.findall(r"^[ \t]*DB_PATH[ \t]*=[ \t]*(.*)$", source, re.MULTILINE)
    if not matches:
        return DEFAULT_DB_PATH

    value = matches[-1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    if not value:
        return DEFAULT_DB_PATH

    path = Path(value)
    return path if path.is_absolute() else Path(__file__).resolve().parent / path


def reset_polling_offset(database_path: Path) -> bool:
    """Remove a bot-specific polling offset while preserving collected rows."""

    if not database_path.exists():
        return False

    owner = database_path.stat()
    connection = sqlite3.connect(database_path, timeout=30)
    deleted = False
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'bot_state'"
        ).fetchone()
        if table is not None:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM bot_state WHERE key = 'next_offset'"
                )
            deleted = cursor.rowcount > 0
    finally:
        connection.close()
        # The helper runs as root, while the collector runs as the normal sudo
        # user. Preserve the database owner's access to any SQLite sidecars.
        for candidate in (
            database_path,
            Path(f"{database_path}-wal"),
            Path(f"{database_path}-shm"),
        ):
            if candidate.exists():
                os.chown(candidate, owner.st_uid, owner.st_gid)
    return deleted


def write_environment_file(path: Path, values: Mapping[str, str]) -> None:
    """Atomically persist configuration as a root-only file."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    if path.exists():
        original = path.read_text(encoding="utf-8")
    else:
        original = TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = set_environment_values(original, values)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".telegram.env.",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(rendered)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary_path, 0o600)
        os.chown(temporary_path, 0, 0)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def describe_message(message: Mapping[str, Any]) -> None:
    sender = message["from"]
    chat = message["chat"]
    sender_name = terminal_safe(
        " ".join(
            str(part)
            for part in (sender.get("first_name"), sender.get("last_name"))
            if part
        )
    )
    sender_username = (
        terminal_safe(f"@{sender['username']}") if sender.get("username") else "no username"
    )
    chat_name = terminal_safe(
        chat.get("title") or chat.get("first_name") or chat.get("type", "unknown")
    )
    message_text = str(message.get("text") or message.get("caption") or "[non-text message]")
    preview = terminal_safe(message_text, limit=120)

    print("\nDetected Telegram message:")
    print(f"  sender:  {sender_name or '(unnamed)'} ({sender_username})")
    print(f"  user ID: {int(sender['id'])}")
    print(f"  chat:    {chat_name} ({chat.get('type', 'unknown')})")
    print(f"  chat ID: {int(chat['id'])}")
    print(f"  message: {preview}")


def main() -> int:
    if os.geteuid() != 0:
        print("error: run this through 'make telegram-env' so the file stays root-only")
        return 2

    print("Telegram environment setup")
    print("The token is entered invisibly and is never printed or placed in shell history.")
    try:
        token = getpass.getpass("BotFather token: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled without changing the environment file.")
        return 130
    if not TOKEN_PATTERN.fullmatch(token):
        print("error: that does not look like a Telegram bot token")
        return 2

    session = requests.Session()
    collector_was_active = False
    configuration_written = False
    try:
        bot = telegram_call(session, token, "getMe")
        if not isinstance(bot, Mapping):
            raise TelegramSetupError("Telegram returned invalid bot information")
        bot_name = terminal_safe(
            f"@{bot['username']}" if bot.get("username") else bot.get("first_name")
        )
        print(f"Authenticated as {bot_name}.")

        collector_was_active = stop_collector_if_active()
        telegram_call(
            session,
            token,
            "deleteWebhook",
            {"drop_pending_updates": False},
        )
        setup_text = f"t: setup {secrets.token_hex(8)}"
        print("\nOn your Mac, open this bot, press Start, and send exactly:")
        print(f"\n  {setup_text}\n")
        print("Older pending setup messages may be acknowledged while locating this one.")
        input("Press Enter here after the message has been sent... ")

        selected_update_id, message = wait_for_setup_message(session, token, setup_text)
        describe_message(message)
        answer = input("Use this user and chat? [Y/n] ").strip().lower()
        if answer not in {"", "y", "yes"}:
            print("Cancelled without changing the environment file.")
            return 1

        config_path = DEFAULT_CONFIG_PATH
        database_path = configured_database_path(config_path)
        if reset_polling_offset(database_path):
            print("Reset the stored Telegram polling position for these credentials.")
        write_environment_file(
            config_path,
            {
                "TELEGRAM_BOT_TOKEN": token,
                "ALLOWED_USER_ID": str(int(message["from"]["id"])),
                "ALLOWED_CHAT_ID": str(int(message["chat"]["id"])),
            },
        )
        configuration_written = True
        try:
            # Do not include the one-time setup phrase in the first daily batch.
            telegram_call(
                session,
                token,
                "getUpdates",
                {"offset": selected_update_id + 1, "limit": 1, "timeout": 0},
            )
        except TelegramSetupError:
            print("warning: the setup message may appear in the first daily summary")
        print(f"\nWrote {config_path} as root:root with mode 0600.")
        print("Next, run from the repository root:  make run")
        return 0
    except (TelegramSetupError, OSError, sqlite3.Error) as error:
        print(f"error: {terminal_safe(error)}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled without changing the environment file.")
        return 130
    finally:
        if collector_was_active and not configuration_written:
            restore_collector()
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
