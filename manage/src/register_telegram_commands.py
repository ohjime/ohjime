"""Register the private bot's thought/action command menu."""

from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import dotenv_values

from configure_telegram_env import TOKEN_PATTERN, TelegramSetupError, telegram_call, terminal_safe


CONFIG_PATH = Path("/etc/ohjime/telegram.env")
COMMANDS = [
    {"command": "thought", "description": "✍ Save a thought — add your text"},
    {"command": "action", "description": "👍 Save an action — add your text"},
]


def main() -> int:
    if os.geteuid() != 0:
        print("error: run this through 'make telegram-commands'")
        return 2
    if not CONFIG_PATH.is_file():
        print("error: run 'make telegram-env' first")
        return 2

    values = dotenv_values(CONFIG_PATH)
    token = str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id_text = str(values.get("ALLOWED_CHAT_ID") or "").strip()
    if not TOKEN_PATTERN.fullmatch(token):
        print("error: Telegram bot token is not configured; run 'make telegram-env'")
        return 2
    try:
        chat_id = int(chat_id_text)
    except ValueError:
        print("error: Telegram chat ID is not configured; run 'make telegram-env'")
        return 2

    session = requests.Session()
    try:
        result = telegram_call(
            session,
            token,
            "setMyCommands",
            {
                "commands": COMMANDS,
                "scope": {"type": "chat", "chat_id": chat_id},
            },
        )
        if result is not True:
            raise TelegramSetupError("Telegram did not confirm the command menu")
    except TelegramSetupError as error:
        print(f"error: {terminal_safe(error)}")
        return 1
    finally:
        session.close()

    print("Registered /thought and /action in the Telegram command menu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
