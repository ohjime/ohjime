"""Summarize the latest dump and inject the summary into the file.

    uv run summarize.py                 # summarize the newest dump in ../../dump
    uv run summarize.py --dry-run       # print the summary, write nothing
    uv run summarize.py --file path.md  # target a specific dump
    uv run summarize.py --dump-dir DIR  # look in a different dump directory

The summary (an Obsidian `[!summary]` callout with tags) is placed directly
below the centered title/date block and above the first note. Re-running
refreshes the block in place instead of duplicating it. Once written, the
dump is locked (front matter `obsidianUIMode: preview`) so it always opens
in reading mode instead of editable live-preview.

Path: the ADK agent talks to the local vLLM server (Qwen/Qwen3-8B-AWQ) through
LiteLLM. Summarization needs no tool-calling, so the server does NOT need the
`--enable-auto-tool-choice` flags — a plain `vllm serve` is enough.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

import dump_ops
from vllm_agent.agent import VLLM_API_BASE, VLLM_MODEL, build_summarizer_agent

APP_NAME = "dump_summarizer"
USER_ID = "dump-owner"

# Default dump directory: repo-root/dump  (this file is manage/src/summarize.py).
DEFAULT_DUMP_DIR = Path(__file__).resolve().parents[2] / "dump"

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RESET = "\033[0m"


def git_pull(from_dir: Path) -> None:
    """Fast-forward the repo containing ``from_dir`` before reading dumps.

    Dumps arrive via Obsidian's git push, so pulling first is what makes the
    "latest" dump actually the latest. Non-fatal: a missing remote, offline
    box, or non-git directory prints a warning and lets summarization proceed
    on whatever is already on disk.
    """
    try:
        toplevel = subprocess.run(
            ["git", "-C", str(from_dir), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"{DIM}git: {from_dir} is not a git repo — skipping pull{RESET}")
        return

    print(f"{DIM}git pull (--ff-only) in {toplevel} …{RESET}")
    result = subprocess.run(
        ["git", "-C", toplevel, "pull", "--ff-only"],
        capture_output=True, text=True,
    )
    out = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        print(f"{DIM}{out or 'Already up to date.'}{RESET}")
    else:
        print(f"{DIM}git pull failed (continuing with local files):\n{out}{RESET}", file=sys.stderr)


def git_push_commit(path: Path, message: str) -> bool:
    """Commit ``path`` alone and push it straight to ``main`` on the remote.

    Stages and commits only this file — restricted with a trailing
    pathspec, so anything else already staged in the repo (e.g. unrelated
    work in progress) is left untouched and never swept into this commit.
    Non-fatal like git_pull: a missing remote, offline box, no changes to
    commit, or a rejected push prints a warning and returns False rather
    than raising, since the summary/lock already succeeded on disk either way.
    """
    try:
        toplevel = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"{DIM}git: {path} is not in a git repo — skipping commit/push{RESET}")
        return False

    rel = os.path.relpath(path, toplevel)

    add = subprocess.run(
        ["git", "-C", toplevel, "add", "--", rel],
        capture_output=True, text=True,
    )
    if add.returncode != 0:
        print(f"{DIM}git add failed:\n{(add.stdout + add.stderr).strip()}{RESET}", file=sys.stderr)
        return False

    staged = subprocess.run(["git", "-C", toplevel, "diff", "--cached", "--quiet", "--", rel])
    if staged.returncode == 0:
        print(f"{DIM}git: no changes to commit for {rel}{RESET}")
        return False

    commit = subprocess.run(
        ["git", "-C", toplevel, "commit", "-m", message, "--", rel],
        capture_output=True, text=True,
    )
    if commit.returncode != 0:
        print(f"{DIM}git commit failed:\n{(commit.stdout + commit.stderr).strip()}{RESET}", file=sys.stderr)
        return False
    print(f"{DIM}{commit.stdout.strip()}{RESET}")

    print(f"{DIM}git push → origin main …{RESET}")
    push = subprocess.run(
        ["git", "-C", toplevel, "push", "origin", "HEAD:main"],
        capture_output=True, text=True,
    )
    out = (push.stdout + push.stderr).strip()
    if push.returncode != 0:
        print(f"{DIM}git push failed:\n{out}{RESET}", file=sys.stderr)
        return False
    print(f"{DIM}{out or 'Pushed to main.'}{RESET}")
    return True


async def run_summary(notes: str) -> str:
    """Send the dump notes to the agent and return its final text response."""
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    runner = Runner(
        agent=build_summarizer_agent(),
        app_name=APP_NAME,
        session_service=session_service,
    )

    prompt = "Summarize this dump.\n\n---\n" + notes + "\n---"
    content = types.Content(role="user", parts=[types.Part(text=prompt)])

    chunks: list[str] = []
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session.id, new_message=content
    ):
        if event.is_final_response() and event.content and event.content.parts:
            chunks.append("".join(part.text or "" for part in event.content.parts))
    return "".join(chunks).strip()


def parse_model_output(raw: str) -> tuple[str, list[str]]:
    """Extract (summary, tags) from the model reply.

    Prefers strict JSON; tolerates markdown fences and stray prose by grabbing
    the first {...} object. Falls back to using the whole reply as the summary.
    """
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            summary = str(data.get("summary", "")).strip()
            tags = data.get("tags", []) or []
            if not isinstance(tags, list):
                tags = [str(tags)]
            if summary:
                return summary, [str(t) for t in tags]
        except json.JSONDecodeError:
            pass
    return raw.strip(), []


async def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize the latest dump file.")
    parser.add_argument("--file", type=Path, help="Summarize this specific dump file.")
    parser.add_argument(
        "--dump-dir",
        type=Path,
        default=Path(os.environ.get("DUMP_DIR", DEFAULT_DUMP_DIR)),
        help="Directory to search for the newest dump (default: repo-root/dump).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the summary without modifying the file.",
    )
    parser.add_argument(
        "--no-pull",
        action="store_true",
        help="Skip the `git pull` that runs before reading the latest dump.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Skip the `git commit`/`push` that runs after writing the summary.",
    )
    args = parser.parse_args()

    if not args.no_pull:
        git_pull(args.file.parent if args.file else args.dump_dir)

    try:
        target = args.file if args.file else dump_ops.latest_dump(args.dump_dir)
    except FileNotFoundError as exc:
        print(f"{DIM}error: {exc}{RESET}", file=sys.stderr)
        return 1

    target = Path(target)
    if not target.exists():
        print(f"{DIM}error: file not found: {target}{RESET}", file=sys.stderr)
        return 1

    text = target.read_text()
    notes = dump_ops.clean_notes(text)
    if not notes:
        print(f"{DIM}error: no notes found in {target.name} to summarize{RESET}", file=sys.stderr)
        return 1

    print(f"{DIM}Summarizing {target.name}  |  model={VLLM_MODEL}  base={VLLM_API_BASE}{RESET}")
    raw = await run_summary(notes)
    if not raw:
        print(f"{DIM}error: empty response from the model{RESET}", file=sys.stderr)
        return 1

    summary, tags = parse_model_output(raw)

    print(f"\n{BOLD}Summary:{RESET} {summary}")
    if tags:
        print(f"{BOLD}Tags:{RESET} {' '.join('#' + t.lstrip('#') for t in tags)}")

    if args.dry_run:
        print(f"\n{DIM}--dry-run: file not modified.{RESET}")
        return 0

    updated = dump_ops.inject_summary(text, summary, tags)
    target.write_text(updated)
    print(f"\n{GREEN}✓ wrote summary into {target}{RESET}")

    dump_ops.lock_note(target)
    print(f"{GREEN}✓ locked {target.name} to preview mode{RESET}")

    if not args.no_push:
        if git_push_commit(target, f"Summarize dump: {target.name}"):
            print(f"{GREEN}✓ committed and pushed {target.name} to main{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
