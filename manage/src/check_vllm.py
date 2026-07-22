"""Diagnose the local vLLM endpoint before running the agent.

    uv run check_vllm.py

Checks, in order:
  1. /v1/models is reachable and lists the configured model.
  2. A plain chat completion works.
  3. Function calling (tool choice) is enabled -- required for the agent's tools.

Uses only the stdlib so it runs even if the ADK/LiteLLM deps aren't installed.
"""

import json
import os
import urllib.error
import urllib.request

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

BASE = os.environ.get("VLLM_API_BASE", "http://localhost:8000/v1").rstrip("/")
KEY = os.environ.get("VLLM_API_KEY", "EMPTY")
MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen3-8B-AWQ")

OK = "\033[32mok\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mwarn\033[0m"


def _request(path: str, payload: dict | None = None):
    url = BASE + path
    headers = {"Authorization": f"Bearer {KEY}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, json.load(resp)


def check_models() -> bool:
    try:
        _, body = _request("/models")
    except (urllib.error.URLError, OSError) as exc:
        print(f"[{FAIL}] cannot reach {BASE}/models: {exc}")
        print("       Is vLLM running? Try: curl " + BASE + "/models")
        return False
    ids = [m.get("id") for m in body.get("data", [])]
    print(f"[{OK}] endpoint reachable; models: {', '.join(ids) or '(none)'}")
    if MODEL not in ids:
        print(f"[{WARN}] configured VLLM_MODEL='{MODEL}' not in the list above")
    return True


def check_chat() -> bool:
    try:
        _, body = _request(
            "/chat/completions",
            {
                "model": MODEL,
                "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
                "max_tokens": 16,
                "temperature": 0,
            },
        )
    except urllib.error.HTTPError as exc:
        print(f"[{FAIL}] chat completion returned HTTP {exc.code}: {exc.read().decode()[:200]}")
        return False
    except (urllib.error.URLError, OSError) as exc:
        print(f"[{FAIL}] chat completion failed: {exc}")
        return False
    content = body["choices"][0]["message"].get("content", "")
    print(f"[{OK}] chat completion works (reply: {content.strip()[:60]!r})")
    return True


def check_tool_calling() -> bool:
    tool = {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get the current time.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    try:
        _, body = _request(
            "/chat/completions",
            {
                "model": MODEL,
                "messages": [{"role": "user", "content": "What time is it? Use the tool."}],
                "tools": [tool],
                "tool_choice": "auto",
                "max_tokens": 64,
                "temperature": 0,
            },
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:300]
        print(f"[{WARN}] tool calling NOT enabled (HTTP {exc.code}).")
        print(f"       server said: {detail}")
        print("       Restart vLLM with: --enable-auto-tool-choice --tool-call-parser hermes")
        print("       (see scripts/serve_vllm.sh). Plain chat still works without it.")
        return False
    except (urllib.error.URLError, OSError) as exc:
        print(f"[{FAIL}] tool-calling probe failed: {exc}")
        return False
    calls = body["choices"][0]["message"].get("tool_calls")
    if calls:
        print(f"[{OK}] tool calling enabled (model requested: {calls[0]['function']['name']})")
        return True
    print(f"[{WARN}] server accepted tools but the model did not emit a tool_call.")
    return False


if __name__ == "__main__":
    print(f"Checking vLLM at {BASE} (model={MODEL})\n")
    if not check_models():
        raise SystemExit(1)
    check_chat()
    check_tool_calling()
