"""Summarize durable batches of Telegram thoughts and actions.

The continuous collector writes authorized Telegram updates to SQLite. This
scheduled process drains bounded chronological batches, gives their normalized
text to the ADK agent, and marks each batch processed only after the agent
succeeds. If processing fails, that batch ID and its rows are retried next time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from telegram_store import (
    DEFAULT_MAX_BATCH_BYTES,
    claim_batch,
    format_batch_for_agent,
    get_pending_high_watermark,
    mark_batch_processed,
    open_database,
    rows_to_payload,
)
from vllm_agent.agent import VLLM_API_BASE, VLLM_MODEL, build_summarizer_agent

APP_NAME = "telegram_dump_summarizer"
USER_ID = "dump-owner"
DEFAULT_DB_PATH = "/var/lib/ohjime/messages.db"
DEFAULT_TIMEZONE = "America/Edmonton"
# Leave room around each piece for the part label and the agent's prompt frame.
MODEL_INPUT_HEADROOM = 256
MODEL_INPUT_BYTES = DEFAULT_MAX_BATCH_BYTES - MODEL_INPUT_HEADROOM
MIN_BATCH_BYTES = 512

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RESET = "\033[0m"


class ModelOutputError(ValueError):
    """Raised when the model does not return a usable summary object."""


def positive_int(value: str) -> int:
    """Argparse converter for positive integer settings."""

    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed < MIN_BATCH_BYTES:
        raise argparse.ArgumentTypeError(f"must be at least {MIN_BATCH_BYTES}")
    return parsed


async def run_summary(notes: str) -> str:
    """Send a normalized Telegram batch to the agent and return its reply."""

    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    runner = Runner(
        agent=build_summarizer_agent(),
        app_name=APP_NAME,
        session_service=session_service,
    )

    prompt = "Summarize this Telegram thought/action batch.\n\n---\n" + notes + "\n---"
    content = types.Content(role="user", parts=[types.Part(text=prompt)])

    chunks: list[str] = []
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=content,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            chunks.append("".join(part.text or "" for part in event.content.parts))
    return "".join(chunks).strip()


def parse_model_output(raw: str) -> tuple[str, list[str]]:
    """Extract and validate ``(summary, tags)`` from the model reply."""

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ModelOutputError("model response did not contain a JSON object")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise ModelOutputError("model response contained invalid JSON") from error
    if not isinstance(data, dict):
        raise ModelOutputError("model response was not a JSON object")

    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ModelOutputError("model response did not contain a non-empty summary")

    tags = data.get("tags", []) or []
    if not isinstance(tags, list):
        raise ModelOutputError("model response tags were not a list")
    return summary.strip(), [str(tag).strip() for tag in tags if str(tag).strip()]


def split_model_input(text: str, max_bytes: int = DEFAULT_MAX_BATCH_BYTES) -> list[str]:
    """Split text on UTF-8 character boundaries for context-safe model calls."""

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for character in text:
        character_bytes = len(character.encode("utf-8"))
        if current and current_bytes + character_bytes > max_bytes:
            chunks.append("".join(current))
            current = []
            current_bytes = 0
        current.append(character)
        current_bytes += character_bytes
    if current:
        chunks.append("".join(current))
    return chunks


async def summarize_model_input(notes: str, *, batch_id: str) -> tuple[str, list[str]]:
    """Run and validate one model call without allowing an empty result."""

    raw = await run_summary(notes)
    if not raw:
        raise RuntimeError(f"empty model response for batch {batch_id}")
    return parse_model_output(raw)


async def process_messages(
    messages: list[dict[str, Any]],
    *,
    batch_id: str,
    max_input_bytes: int = DEFAULT_MAX_BATCH_BYTES,
) -> tuple[str, list[str]]:
    """Run the existing ADK summarization function for one claimed batch."""

    model_chunk_bytes = min(max_input_bytes, DEFAULT_MAX_BATCH_BYTES) - MODEL_INPUT_HEADROOM
    if model_chunk_bytes < 4:
        raise ValueError("max_input_bytes is too small for UTF-8 model input")

    notes = format_batch_for_agent(messages)
    chunks = split_model_input(notes, max_bytes=model_chunk_bytes)
    if len(chunks) == 1:
        return await summarize_model_input(chunks[0], batch_id=batch_id)

    partials: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        partial_summary, partial_tags = await summarize_model_input(
            f"[Part {index} of {len(chunks)}]\n{chunk}",
            batch_id=batch_id,
        )
        partials.append({"summary": partial_summary, "tags": partial_tags})

    while len(partials) > 1:
        synthesis_input = (
            "Combine these ordered partial summaries into faithful partial summaries:\n"
            + json.dumps(partials, ensure_ascii=False, separators=(",", ":"))
        )
        synthesis_chunks = split_model_input(
            synthesis_input,
            max_bytes=model_chunk_bytes,
        )
        reduced: list[dict[str, Any]] = []
        for index, chunk in enumerate(synthesis_chunks, start=1):
            combined_summary, combined_tags = await summarize_model_input(
                f"[Synthesis part {index} of {len(synthesis_chunks)}]\n{chunk}",
                batch_id=batch_id,
            )
            reduced.append({"summary": combined_summary, "tags": combined_tags})
        if len(reduced) >= len(partials):
            raise ModelOutputError(
                "partial synthesis did not reduce the result; batch remains queued"
            )
        partials = reduced

    return str(partials[0]["summary"]), [str(tag) for tag in partials[0]["tags"]]


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize unprocessed Telegram thoughts/actions from SQLite."
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(os.environ.get("DB_PATH", "").strip() or DEFAULT_DB_PATH),
        help="SQLite database written by telegram_collector.py.",
    )
    parser.add_argument(
        "--timezone",
        default=os.environ.get("LOCAL_TIMEZONE", "").strip() or DEFAULT_TIMEZONE,
        help="IANA timezone used for message timestamps.",
    )
    parser.add_argument(
        "--max-batch-bytes",
        type=positive_int,
        default=os.environ.get("MAX_BATCH_BYTES", "").strip()
        or str(DEFAULT_MAX_BATCH_BYTES),
        help="Conservative UTF-8 input limit used to stay within model context.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the agent but leave the claimed batch unprocessed for retry.",
    )
    args = parser.parse_args()

    try:
        local_timezone = ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError:
        print(f"{DIM}error: unknown timezone: {args.timezone}{RESET}", file=sys.stderr)
        return 2

    connection = open_database(args.db_path)
    try:
        through_id = get_pending_high_watermark(connection)
        if through_id is None:
            print(f"{DIM}No unprocessed Telegram messages.{RESET}")
            return 0

        processed_batches = 0
        processed_messages = 0

        while True:
            claimed = claim_batch(
                connection,
                max_batch_bytes=args.max_batch_bytes,
                through_id=through_id,
            )
            if claimed is None:
                print(
                    f"\n{GREEN}✓ run snapshot drained: {processed_batches} batch(es), "
                    f"{processed_messages} message(s){RESET}"
                )
                return 0

            batch_id, rows = claimed
            messages = rows_to_payload(rows, local_timezone)
            print(
                f"{DIM}Summarizing {len(messages)} Telegram message(s)"
                f"  |  batch={batch_id}  |  model={VLLM_MODEL}  base={VLLM_API_BASE}{RESET}"
            )

            try:
                summary, tags = await process_messages(
                    messages,
                    batch_id=batch_id,
                    max_input_bytes=args.max_batch_bytes,
                )
            except Exception as error:  # noqa: BLE001 - preserve the batch on any failure
                print(
                    f"{DIM}error: batch {batch_id} failed ({type(error).__name__}); "
                    f"it remains queued for retry{RESET}",
                    file=sys.stderr,
                )
                return 1

            print(f"\n{BOLD}Summary:{RESET} {summary}")
            if tags:
                rendered_tags = " ".join("#" + tag.lstrip("#") for tag in tags)
                print(f"{BOLD}Tags:{RESET} {rendered_tags}")

            if args.dry_run:
                print(f"\n{DIM}--dry-run: batch {batch_id} remains unprocessed for retry.{RESET}")
                return 0

            completed = mark_batch_processed(
                connection,
                batch_id,
                summary=summary,
                tags=tags,
            )
            if completed != len(messages):
                print(
                    f"{DIM}error: batch {batch_id} changed while processing "
                    f"({completed}/{len(messages)} rows completed){RESET}",
                    file=sys.stderr,
                )
                return 1

            processed_batches += 1
            processed_messages += completed
            print(f"\n{GREEN}✓ processed batch {batch_id} ({completed} message(s)){RESET}")
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
