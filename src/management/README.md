# adk-demo — Google ADK on local vLLM

A minimal [Google ADK](https://adk.dev) agent whose LLM is served by a **local,
self-hosted vLLM** instance. ADK reaches vLLM through
[LiteLLM](https://docs.litellm.ai/docs/tutorials/google_adk), which speaks
vLLM's OpenAI-compatible API.

```
ADK  LlmAgent
  └── LiteLlm("hosted_vllm/<model>", api_base=…/v1)
        └── vLLM OpenAI server  (http://localhost:8000/v1)
              └── Qwen/Qwen3-8B-AWQ
```

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) (already installed here).
- A running vLLM OpenAI server. One is already up on this machine serving
  `Qwen/Qwen3-8B-AWQ` on port 8000. Verify:

  ```bash
  curl http://localhost:8000/v1/models
  ```

## Setup

```bash
cd apps/adk-demo
cp .env.example .env      # defaults already match the local vLLM server
uv sync                   # create .venv and install google-adk + litellm
```

## Run

```bash
uv run check_vllm.py      # 1) sanity-check the endpoint (recommended first)
uv run main.py            # 2) scripted demo (chat turn + a tool-using turn)
uv run main.py --chat     # 3) interactive REPL

uv run adk web            # 4) ADK's web UI; pick the `vllm_agent` app
uv run adk run vllm_agent # 5) ADK's terminal chat
```

## Enabling tools (function calling)

The agent ships three tools (`roll_dice`, `is_prime`, `get_current_time`).
vLLM only performs OpenAI-style function calling when started with
`--enable-auto-tool-choice --tool-call-parser hermes` (the parser is
model-specific; `hermes` is what Qwen3 uses). Without them, plain chat works but
tool calls fail with HTTP 400. `uv run check_vllm.py` reports the current state.

There are two ways to turn them on:

**Durable — the systemd-managed service on this box (recommended).**
vLLM here is run by the `vllm.service` systemd unit, configured via
`/etc/vllm/vllm.env`. This script adds the flags to that file's `VLLM_EXTRA` and
restarts the service, so tools stay on across reboots. Run it once:

```bash
sudo ./scripts/enable_service_tools.sh
```

**Ad-hoc — a manual foreground server.** Stops nothing permanently; good for
experiments:

```bash
./scripts/serve_vllm.sh
```

## Alternative backend: Gemma 4 in Docker (Turing-patched vLLM)

Stock vLLM cannot run Gemma 4 on this machine's RTX 2080 Ti: the model's
full-attention layers use head_size 512, which needs ~96 KB of shared memory
per block while Turing (SM 7.5) caps out at 64 KB, so every attention backend
fails ([vllm#38918](https://github.com/vllm-project/vllm/issues/38918)).
[docker/](docker/) builds a `vllm/vllm-openai:v0.25.0` image with the
approved-but-unmerged upstream fix
([PR #39018](https://github.com/vllm-project/vllm/pull/39018)) baked in, and
serves **`google/gemma-4-E2B-it-qat-w4a16-ct`** — Google's official QAT INT4
quant (~8.3 GB, ungated), the only Gemma 4 that fits in 11 GB VRAM. Tool
calling is enabled (`--tool-call-parser gemma4`), so the demo works unchanged.

One-time host setup (Docker has no GPU access until the NVIDIA Container
Toolkit is installed):

```bash
sudo ./docker/setup-nvidia-container-toolkit.sh
```

Run (the container replaces the Qwen3 service on port 8000 — stop one before
starting the other; both also need the whole GPU):

```bash
sudo systemctl stop vllm.service
cd docker && docker compose up -d --build   # first start downloads ~8.3 GB
curl http://localhost:8000/v1/models        # wait for the model id to appear
```

Then point the agent at it in `.env`:

```bash
VLLM_MODEL=google/gemma-4-E2B-it-qat-w4a16-ct
```

Switch back with `docker compose down` + `sudo systemctl start vllm.service`
(and restore `VLLM_MODEL`). Serving flags (fp16, 8K context, text-only,
eager mode — all sized for the 11 GB card) are documented inline in
[docker/compose.yaml](docker/compose.yaml).

## Configuration (`.env`)

| Variable               | Default                     | Meaning                                             |
| ---------------------- | --------------------------- | --------------------------------------------------- |
| `VLLM_API_BASE`        | `http://localhost:8000/v1`  | vLLM OpenAI endpoint (keep the `/v1`).              |
| `VLLM_MODEL`           | `Qwen/Qwen3-8B-AWQ`         | Model id exactly as shown by `/v1/models`.          |
| `VLLM_API_KEY`         | `EMPTY`                     | Any non-empty value unless vLLM ran with `--api-key`.|
| `VLLM_ENABLE_THINKING` | `false`                     | Toggle Qwen3's `<think>` reasoning traces.          |

## Layout

```
adk-demo/
├── pyproject.toml          # uv project + deps (google-adk, litellm)
├── .env.example            # copy to .env
├── main.py                 # standalone Runner-based demo (uv run main.py)
├── check_vllm.py           # stdlib-only endpoint/tool-calling diagnostics
├── scripts/serve_vllm.sh   # launch vLLM with tool-calling flags
├── docker/                 # Gemma 4 on the 2080 Ti (Turing-patched vLLM image)
│   ├── Dockerfile          # vllm-openai:v0.25.0 + PR #39018 patch
│   ├── compose.yaml        # serve flags sized for 11 GB VRAM
│   ├── patches/apply_pr39018.py             # verify-and-replace patcher
│   └── setup-nvidia-container-toolkit.sh    # one-time host GPU setup (sudo)
└── vllm_agent/             # ADK agent package (discovered by `adk web`/`adk run`)
    ├── __init__.py
    └── agent.py            # root_agent = LlmAgent(model=LiteLlm("hosted_vllm/…"))
```

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

root_agent = LlmAgent(name="vllm_agent", model=vllm_model, tools=[...])
```
