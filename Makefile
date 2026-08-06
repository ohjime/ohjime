.PHONY: docs clean telegram-collector daily-summary

ARGS ?=

docs:
	@cd docs && npm install
	@cd docs && npm run start

clean:
	@cd docs && npm run clear
	@cd docs && npm cache clean --force
	@rm -rf docs/node_modules

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
