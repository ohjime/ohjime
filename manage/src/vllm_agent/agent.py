"""A Google ADK agent that summarizes dump files, served by local vLLM.

The bridge is LiteLLM: ADK's ``LiteLlm`` model wrapper talks to any
OpenAI-compatible endpoint. For a self-hosted vLLM server, LiteLLM uses the
``hosted_vllm/<model-id>`` provider prefix plus an explicit ``api_base``.

The model is ``Qwen/Qwen3-8B-AWQ`` — the sweet spot for an 11 GB RTX 2080 Ti
(Turing, SM 7.5): the AWQ 4-bit weights are ~5.5 GB, leaving plenty of room for
a 16K KV cache, and it needs no exotic kernels (vLLM falls back to the standard
AWQ GEMM path on SM 7.5). Summarization is pure text-in/text-out, so no
tool-calling flags are required on the server.

Docs:
  - https://adk.dev/agents/models/vllm/
  - https://docs.litellm.ai/docs/tutorials/google_adk
"""

import os

from dotenv import find_dotenv, load_dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

# Load config from the project's .env (searched upward from this file), so this
# module works both under `adk web`/`adk run` and when imported by summarize.py.
load_dotenv(find_dotenv())

VLLM_API_BASE = os.environ.get("VLLM_API_BASE", "http://localhost:8000/v1")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen3-8B-AWQ")
VLLM_API_KEY = os.environ.get("VLLM_API_KEY", "EMPTY")
ENABLE_THINKING = os.environ.get("VLLM_ENABLE_THINKING", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# --- Instruction ------------------------------------------------------------
# The dumps are a stream-of-consciousness "Chain of Thoughts and Actions": a
# series of `[!start-thought]` / `[!start-action]` callouts. We want a compact
# summary plus a few Obsidian tags. Strict JSON keeps the output machine-parsable
# (summarize.py falls back to treating the whole reply as the summary if the
# model ever strays from the format).
SUMMARIZER_INSTRUCTION = """\
You summarize a personal "Chain of Thoughts and Actions" note (a dump).
The note is a stream of timestamped thoughts and actions.

Write a faithful, concise summary of what the author was thinking about and did:
2-4 sentences, third person, no fluff, no preamble. Then choose 3-6 short
Obsidian tags (lowercase, hyphenated, no leading '#') that capture the main
topics.

Respond with ONLY a single JSON object, no markdown fences, exactly:
{"summary": "<the summary>", "tags": ["tag-one", "tag-two"]}
"""


# --- Model ------------------------------------------------------------------
# `hosted_vllm/` tells LiteLLM this is a self-hosted vLLM OpenAI-compatible
# server; the rest of the string is the model id as reported by /v1/models.
vllm_model = LiteLlm(
    model=f"hosted_vllm/{VLLM_MODEL}",
    api_base=VLLM_API_BASE,
    api_key=VLLM_API_KEY,
    # Passed straight through to vLLM's chat/completions call. Qwen3 reads
    # `chat_template_kwargs.enable_thinking` to toggle its reasoning traces;
    # keep it off for fast, clean, JSON-only output.
    extra_body={"chat_template_kwargs": {"enable_thinking": ENABLE_THINKING}},
)


def build_summarizer_agent() -> LlmAgent:
    """Construct the dump-summarizer agent (no tools; pure text summarization)."""
    return LlmAgent(
        name="dump_summarizer",
        model=vllm_model,
        description="Summarizes personal dump notes served by a local vLLM server.",
        instruction=SUMMARIZER_INSTRUCTION,
        # Low temperature => stable, faithful summaries and reliable JSON.
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=512,
        ),
    )


# ADK discovers `root_agent` for `adk web` / `adk run vllm_agent`.
root_agent = build_summarizer_agent()
