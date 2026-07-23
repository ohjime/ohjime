"""Pure text operations on dump files — no ADK / network dependencies.

Kept deliberately free of heavy imports so the parsing/injection logic can be
unit-tested (and reasoned about) without a GPU or a running vLLM server.

A dump file looks like::

    <div style="text-align: center;">
      <h1>Chain of Thoughts and Actions</h1>
      <h3 ...>July 21, 2026</h3>
    </div>
    > [!start-thought] @ 3:42 AM
    ...

The agent-written summary is injected *between* that centered title/date block
and the first note, wrapped in HTML-comment markers so re-runs replace it
in place instead of stacking duplicates.
"""

from __future__ import annotations

import re
from pathlib import Path

SUMMARY_START = "<!-- adk-summary:start -->"
SUMMARY_END = "<!-- adk-summary:end -->"

# Matches our marked block plus any blank lines hugging it, so replacing it
# never leaves ragged spacing behind.
_SUMMARY_BLOCK_RE = re.compile(
    r"\n*" + re.escape(SUMMARY_START) + r".*?" + re.escape(SUMMARY_END) + r"\n*",
    re.DOTALL,
)


def latest_dump(dump_dir: Path) -> Path:
    """Return the most recently modified ``*.md`` file in ``dump_dir``.

    Raises FileNotFoundError if the directory has no markdown files.
    """
    dump_dir = Path(dump_dir)
    candidates = sorted(
        dump_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not candidates:
        raise FileNotFoundError(f"no .md files found in {dump_dir}")
    return candidates[0]


def split_header_body(text: str) -> tuple[str, str]:
    """Split a dump into (header, body).

    The header is the leading centered ``<div>…</div>`` title/date block, up to
    and including the first ``</div>``. If there is no such block, the header is
    empty and the whole document is the body.
    """
    match = re.search(r"</div>", text, re.IGNORECASE)
    if not match:
        return "", text
    cut = match.end()
    return text[:cut], text[cut:]


def remove_summary_block(text: str) -> str:
    """Strip a previously injected summary block (if any) from ``text``."""
    return _SUMMARY_BLOCK_RE.sub("\n", text, count=1)


def clean_notes(text: str) -> str:
    """The actual notes: document minus the header and any existing summary."""
    _, body = split_header_body(text)
    return remove_summary_block(body).strip()


def build_summary_block(summary: str, tags: list[str] | None = None) -> str:
    """Render the Obsidian ``[!summary]`` callout, marker-wrapped."""
    summary_lines = [line.rstrip() for line in summary.strip().splitlines()] or [""]
    quoted = "\n".join(f"> {line}".rstrip() for line in summary_lines)

    lines = [SUMMARY_START, "> [!summary] Summary", quoted]
    cleaned_tags = _normalize_tags(tags or [])
    if cleaned_tags:
        lines.append(">")
        lines.append("> **Tags:** " + " ".join(f"#{t}" for t in cleaned_tags))
    lines.append(SUMMARY_END)
    return "\n".join(lines)


def inject_summary(text: str, summary: str, tags: list[str] | None = None) -> str:
    """Return ``text`` with the summary placed just below the title/date block.

    Idempotent: any existing marked block is removed first, so repeated runs
    refresh the summary rather than appending a new one.
    """
    header, body = split_header_body(text)
    body_clean = remove_summary_block(body).lstrip("\n")
    block = build_summary_block(summary, tags)

    parts = []
    if header.strip():
        parts.append(header.rstrip("\n"))
    parts.append(block)
    if body_clean.strip():
        parts.append(body_clean.rstrip("\n"))

    result = "\n\n".join(parts)
    return result + "\n"


# Recognizes a front-matter block only when the file's very first
# characters are "---" — a "---" later in the body (e.g. a markdown
# horizontal rule, which dump logs never have but other notes might) is
# never mistaken for one.
_FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)

LOCK_FRONT_MATTER = {"obsidianUIMode": "preview"}


def _set_front_matter_field(block: str, key: str, value: str) -> str:
    """Set ``key: value`` on its own line inside a front-matter body.

    Edits the existing ``key:`` line in place if present (matched only at
    the start of a line, so nothing else in the block is touched); appends
    a new line otherwise. Every other line — lists, nested maps, comments,
    ordering — passes through untouched, since we never parse the block
    into a dict and re-render it.
    """
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    line = f"{key}: {value}"
    if pattern.search(block):
        return pattern.sub(line, block, count=1)
    block = block.rstrip("\n")
    return f"{block}\n{line}" if block else line


def set_front_matter(text: str, updates: dict[str, str]) -> str:
    """Merge ``updates`` into ``text``'s front matter, touching nothing else.

    If ``text`` already starts with a ``---``-delimited block, only the
    named keys are edited (or appended) within it; the rest of the block
    and the entire body are passed through byte-for-byte. If there is no
    front-matter block, one is created at the top of the file and the body
    — dump logs included — is left exactly as it was.
    """
    match = _FRONT_MATTER_RE.match(text)
    block, body = (match.group(1), text[match.end():]) if match else ("", text)

    for key, value in updates.items():
        block = _set_front_matter_field(block, key, value)

    return f"---\n{block}\n---\n{body}"


def lock_note_text(text: str) -> str:
    """Return ``text`` with front matter set to force Obsidian preview mode."""
    return set_front_matter(text, LOCK_FRONT_MATTER)


def lock_note(path: Path) -> Path:
    """Lock the note at ``path`` so Obsidian always opens it in preview mode.

    Reads the file, merges the lock keys into its front matter (creating
    the block if the note doesn't have one yet), and writes it back in
    place. Idempotent — re-locking an already-locked note is a no-op write.
    """
    path = Path(path)
    path.write_text(lock_note_text(path.read_text()))
    return path


def _normalize_tags(tags: list[str]) -> list[str]:
    """Make model-supplied tags Obsidian-safe and de-duplicated."""
    seen: list[str] = []
    for raw in tags:
        tag = str(raw).strip().lstrip("#").strip()
        tag = re.sub(r"\s+", "-", tag)
        tag = re.sub(r"[^0-9A-Za-z/_-]", "", tag)
        if tag and tag.lower() not in {s.lower() for s in seen}:
            seen.append(tag)
    return seen
