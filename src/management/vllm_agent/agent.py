"""A Google ADK agent whose LLM is served by a local vLLM instance.

The bridge is LiteLLM: ADK's ``LiteLlm`` model wrapper talks to any
OpenAI-compatible endpoint. For a self-hosted vLLM server, LiteLLM uses the
``hosted_vllm/<model-id>`` provider prefix plus an explicit ``api_base``.

Docs:
  - https://adk.dev/agents/models/vllm/
  - https://docs.litellm.ai/docs/tutorials/google_adk
"""

import os
import random
from datetime import datetime, timezone

from dotenv import find_dotenv, load_dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

# Load config from the project's .env (searched upward from this file), so this
# module works both under `adk web`/`adk run` and when imported by main.py.
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


# --- Tools -----------------------------------------------------------------
# Plain Python functions become ADK tools. Type hints + docstrings are turned
# into the function-calling schema the model sees, so keep them accurate.
# NOTE: tool calling requires the vLLM server to be started with
# `--enable-auto-tool-choice --tool-call-parser hermes` (see scripts/serve_vllm.sh).


def roll_dice(sides: int = 6) -> dict:
    """Roll a single die and return the result.

    Args:
        sides: Number of sides on the die (minimum 2, default 6).

    Returns:
        A dict with the requested number of sides and the rolled value.
    """
    sides = max(2, int(sides))
    return {"sides": sides, "result": random.randint(1, sides)}


def is_prime(number: int) -> dict:
    """Test whether an integer is prime.

    Args:
        number: The integer to test.

    Returns:
        A dict with the number and whether it is prime.
    """
    n = int(number)
    prime = n >= 2 and all(n % d for d in range(2, int(n**0.5) + 1))
    return {"number": n, "is_prime": prime}


def get_current_time() -> dict:
    """Return the current UTC time as an ISO-8601 string."""
    return {"utc_time": datetime.now(timezone.utc).isoformat()}


# --- Model ------------------------------------------------------------------
# `hosted_vllm/` tells LiteLLM this is a self-hosted vLLM OpenAI-compatible
# server; the rest of the string is the model id as reported by /v1/models.
vllm_model = LiteLlm(
    model=f"hosted_vllm/{VLLM_MODEL}",
    api_base=VLLM_API_BASE,
    api_key=VLLM_API_KEY,
    # Passed straight through to vLLM's chat/completions call. Qwen3 reads
    # `chat_template_kwargs.enable_thinking` to toggle its reasoning traces.
    extra_body={"chat_template_kwargs": {"enable_thinking": ENABLE_THINKING}},
)


# --- Agent ------------------------------------------------------------------
TOOLS = [roll_dice, is_prime, get_current_time]


def build_agent(with_tools: bool = True) -> LlmAgent:
    """Construct the vLLM-backed agent.

    Args:
        with_tools: Attach the function-calling tools. Set False to talk to a
            vLLM server that was NOT started with `--enable-auto-tool-choice`
            (attaching tools would make every request fail with HTTP 400).
    """
    return LlmAgent(
        name="vllm_agent",
        model=vllm_model,
        description="A helpful assistant powered by a local, self-hosted vLLM server.",
        instruction=(
            "You are a concise, helpful assistant running on a locally hosted vLLM "
            f"server (model: {VLLM_MODEL}). Use the tools whenever they help. If a "
            "question needs several steps, call the tools one after another and do "
            "NOT stop until every step is done -- e.g. after rolling a die, actually "
            "call the prime-check tool on the result rather than just describing it. "
            "Only give your final plain-language answer once all tool calls are done."
        ),
        # Low temperature makes multi-step tool use far more reliable on an 8B model.
        generate_content_config=types.GenerateContentConfig(temperature=0.2),
        tools=TOOLS if with_tools else [],
    )


# ADK discovers `root_agent` for `adk web` / `adk run` (tools on -- run
# scripts/serve_vllm.sh so the server supports function calling).
root_agent = build_agent(with_tools=True)
