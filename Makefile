.PHONY: docs clean daily-summary

ARGS ?=

docs:
	@cd docs && npm install
	@cd docs && npm run start

clean:
	@cd docs && npm run clear
	@cd docs && npm cache clean --force
	@rm -rf docs/node_modules

# Summarize the latest dump: git pull, run the local Qwen3 agent, and write the
# summary in below the title/date block. Re-running refreshes it in place.
#
#   make daily-summary                  # summarize and write
#   make daily-summary ARGS=--dry-run   # preview, write nothing
daily-summary:
	@cd manage/src && uv run summarize.py $(ARGS)
