.PHONY: docs clean setup telegram-env telegram-commands run telegram-collector daily-summary

ARGS ?=
SETUP_ARGS ?=
UBUNTU_PYTHON ?= python3

docs:
	@cd docs && npm install
	@cd docs && npm run start

clean:
	@cd docs && npm run clear
	@cd docs && npm cache clean --force
	@rm -rf docs/node_modules

# Install or update the complete Ubuntu stack. On the first run this creates
# the protected Telegram environment file with placeholders.
#
#   make setup
#   make setup SETUP_ARGS=--no-start
setup:
	@$(UBUNTU_PYTHON) manage/src/ubuntu_commands.py setup $(SETUP_ARGS)

# Securely prompt for the BotFather token, discover the sender/chat IDs from a
# message sent to the bot, and write /etc/ohjime/telegram.env as root:root 0600.
telegram-env:
	@$(UBUNTU_PYTHON) manage/src/ubuntu_commands.py telegram-env

# Register /thought and /action in the configured private Telegram chat.
telegram-commands:
	@$(UBUNTU_PYTHON) manage/src/ubuntu_commands.py telegram-commands

# After `make setup` and `make telegram-env`, validate the credentials and
# enable the collector and 10 PM timer. The model server installed by setup is
# left running rather than restarted.
run:
	@$(UBUNTU_PYTHON) manage/src/ubuntu_commands.py run

# Continuously collect Telegram messages into SQLite. Required Telegram
# credentials and DB_PATH are read from the environment.
telegram-collector:
	@cd manage/src && uv run telegram_collector.py

# Drain waiting SQLite messages in context-sized batches with the local Qwen3
# agent. A failed chunk keeps the same stable batch ID for retry.
#
#   make daily-summary                  # drain and complete waiting messages
#   make daily-summary ARGS=--dry-run   # preview one batch, leave it queued
daily-summary:
	@cd manage/src && uv run summarize.py $(ARGS)
