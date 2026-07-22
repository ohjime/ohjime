# dump-summarizer — auto-summarize dumps with a local vLLM agent

A [Google ADK](https://adk.dev) agent that reads the newest note in
[`dump/`](../../dump) and writes a short summary (plus Obsidian tags) into the
file — placed right below the centered title/date block and above the first
note. The LLM is a **local, self-hosted vLLM** server reached through
[LiteLLM](https://docs.litellm.ai/docs/tutorials/google_adk).

```
summarize.py
  └── ADK Runner  →  LlmAgent  →  LiteLlm("hosted_vllm/<model>", api_base=…/v1)
                                    └── vLLM OpenAI server (http://localhost:8000/v1)
                                          └── Qwen/Qwen3-8B-AWQ
```

## The model: Qwen3-8B-AWQ on the RTX 2080 Ti

The default is **`Qwen/Qwen3-8B-AWQ`** — the seamless pick for the 11 GB
2080 Ti (Turing, SM 7.5), and the model your `vllm.service` already serves:

- **Fits comfortably.** AWQ 4-bit weights are ~5.5 GB, leaving ample room for a
  16K KV cache in 11 GB.
- **No exotic kernels.** Marlin/Machete need SM ≥ 8.0; on SM 7.5 vLLM falls back
  to the standard AWQ GEMM path — slower than Ampere, but it just works.
- **No Turing patching.** Unlike Gemma 4 (whose head_size 512 exceeds Turing's
  64 KB shared-memory cap and needs an unmerged upstream fix), Qwen3-8B runs on
  stock vLLM. That whole Docker/patch setup has been removed.

If you later want more quality and can trade away context length, `Qwen3-14B-AWQ`
(~9.3 GB) is the practical ceiling on this card — leave the KV cache small
(`--max-model-len 4096` or so). It is *not* as seamless; 8B-AWQ is the daily driver.

## Install on a fresh Ubuntu machine

The repo bootstraps itself. On any Ubuntu box with an NVIDIA GPU and driver:

```bash
git clone <this-repo> ohjime
cd ohjime/manage/src
sudo ./deploy/install.sh
```

That is the whole setup. It is idempotent — re-run it any time. It installs:

| Thing | Where |
| --- | --- |
| `uv` (if missing) | `~/.local/bin/uv` |
| vLLM venv, **Python 3.12**, `vllm==0.25.0` | `~/.local/share/ohjime/vllm` |
| Summarizer deps (`uv sync`) | `manage/src/.venv` |
| Model server config | `/etc/ohjime/vllm.env` |
| `ohjime-vllm.service` | serves Qwen3-8B-AWQ on :8000 |
| `ohjime-summarizer.service` + `.timer` | hourly summarize run |

Two pins matter and are deliberate:

- **Python 3.12**, not the system Python. Ubuntu 26.04 ships Python 3.14, which
  vLLM has no wheels for. `uv` fetches 3.12 automatically.
- **`vllm==0.25.0`**, proven working with Qwen3-8B-AWQ on Turing (SM 7.5).

The installer also runs preflight checks (NVIDIA driver present, GPU compute
capability, free disk) and disables any pre-existing hand-rolled `vllm.service`,
which would otherwise fight it for port 8000 and the GPU.

Flags: `--no-timer` (install without the hourly schedule), `--no-start`
(don't start the model server), `--vllm-venv DIR` (custom venv location).
Remove everything with `sudo ./deploy/uninstall.sh [--purge]`.

### Managing it

```bash
systemctl status ohjime-vllm              # model server
sudo systemctl start ohjime-summarizer    # summarize now
journalctl -u ohjime-summarizer -f        # watch a run
systemctl list-timers ohjime-summarizer.timer
```

### Manual setup (no systemd)

```bash
cd manage/src
cp .env.example .env
uv sync
# and serve the model yourself:
vllm serve Qwen/Qwen3-8B-AWQ --dtype float16 --enforce-eager --max-model-len 16384
```

Summarization is plain text-in/text-out, so the server needs **no** tool-calling
flags. Verify any server with `curl http://localhost:8000/v1/models`.

## Run

```bash
uv run check_vllm.py      # optional: sanity-check the endpoint first
uv run summarize.py       # git pull, summarize the newest dump, write it in
uv run summarize.py --dry-run       # print the summary, change nothing
uv run summarize.py --no-pull       # don't git pull first
uv run summarize.py --file ../../dump/LOG-2026-07-21.md   # a specific dump
```

What it does:

1. Runs `git pull --ff-only` in the repo first (dumps arrive via Obsidian's git
   push, so this is what makes "latest" actually the latest). Non-fatal — if the
   box is offline or the remote can't fast-forward, it warns and proceeds on the
   local files. Skip it with `--no-pull`.
2. Finds the most recently modified `*.md` in `dump/` (or `--file`).
3. Extracts the notes (everything below the `<div>` title/date block).
4. Asks the agent for a 2–4 sentence summary + 3–6 Obsidian tags.
5. Injects an Obsidian `[!summary]` callout just under the title/date and above
   the first note. Re-running **refreshes** the block in place (it's wrapped in
   `<!-- adk-summary:start/end -->` markers) rather than duplicating it.

Example of what gets inserted:

```markdown
<div style="text-align: center;">
  <h1>Chain of Thoughts and Actions</h1>
  <h3 ...>July 21, 2026</h3>
</div>

<!-- adk-summary:start -->
> [!summary] Summary
> The author sketched a dump-template with an auto-filled summary, mused about
> encrypting dumps with classic ciphers on push, and set out to wire the ADK
> agent up to summarize dumps on the local vLLM box.
>
> **Tags:** #dumps #local-llm #encryption #adk
<!-- adk-summary:end -->

> [!start-thought] @ 3:42 AM
...
```

## Configuration (`.env`)

| Variable               | Default                     | Meaning                                              |
| ---------------------- | --------------------------- | ---------------------------------------------------- |
| `VLLM_API_BASE`        | `http://localhost:8000/v1`  | vLLM OpenAI endpoint (keep the `/v1`).               |
| `VLLM_MODEL`           | `Qwen/Qwen3-8B-AWQ`         | Model id exactly as shown by `/v1/models`.           |
| `VLLM_API_KEY`         | `EMPTY`                     | Any non-empty value unless vLLM ran with `--api-key`.|
| `VLLM_ENABLE_THINKING` | `false`                     | Toggle Qwen3's `<think>` reasoning traces.           |
| `DUMP_DIR`             | `../../dump`                | Where to look for dumps (CLI `--dump-dir` overrides).|

## Layout

```
manage/src/
├── pyproject.toml          # uv project + deps (google-adk, litellm)
├── .env.example            # copy to .env
├── summarize.py            # entrypoint: git pull → read latest dump → summarize → inject
├── dump_ops.py             # pure text ops (find/split/inject); no ADK deps
├── check_vllm.py           # stdlib-only endpoint diagnostics
├── deploy/                 # self-contained systemd install (fresh Ubuntu box)
│   ├── install.sh              # idempotent installer  (sudo ./deploy/install.sh)
│   ├── uninstall.sh            # clean removal
│   ├── vllm.env.example        # → /etc/ohjime/vllm.env
│   ├── ohjime-vllm.service     # model server unit template
│   ├── ohjime-summarizer.service   # one-shot summarize run
│   └── ohjime-summarizer.timer     # hourly schedule
├── scripts/
│   ├── serve_vllm.sh           # ad-hoc foreground vLLM (with tool flags)
│   └── enable_service_tools.sh # legacy: tool flags on a hand-rolled vllm.service
└── vllm_agent/             # ADK agent package (discovered by `adk web`/`adk run`)
    ├── __init__.py
    └── agent.py            # root_agent = summarizer LlmAgent(model=LiteLlm(...))
```

`scripts/` and `check_vllm.py`'s tool-calling probe are carried over from the
original demo; the summarizer itself uses **no** tools, so they're only relevant
if you extend the agent later.

## How the vLLM binding works

`vllm_agent/agent.py`:

```python
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

vllm_model = LiteLlm(
    model="hosted_vllm/Qwen/Qwen3-8B-AWQ",   # hosted_vllm/ = self-hosted vLLM
    api_base="http://localhost:8000/v1",
    api_key="EMPTY",
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)

root_agent = LlmAgent(name="dump_summarizer", model=vllm_model, ...)
```
