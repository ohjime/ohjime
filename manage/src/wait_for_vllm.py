"""Wait for the configured vLLM model endpoint to become usable.

The Ubuntu one-shot processor uses this during cold boots. It intentionally
reads the same project ``.env`` variables as the ADK client, including an API
key when the endpoint requires one.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

API_BASE = os.environ.get("VLLM_API_BASE", "http://localhost:8000/v1").rstrip("/")
API_KEY = os.environ.get("VLLM_API_KEY", "EMPTY")
MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen3-8B-AWQ")


def model_is_ready(request_timeout: float) -> bool:
    """Return whether ``/models`` advertises the configured model."""

    request = urllib.request.Request(
        f"{API_BASE}/models",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    with urllib.request.urlopen(request, timeout=request_timeout) as response:
        payload = json.load(response)
    models = payload.get("data", []) if isinstance(payload, dict) else []
    return MODEL in {item.get("id") for item in models if isinstance(item, dict)}


def wait_until_ready(timeout: int, interval: float = 5.0) -> bool:
    """Poll until ready or ``timeout`` seconds elapse without exposing secrets."""

    deadline = time.monotonic() + timeout
    last_error = "model not advertised"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(f"vLLM readiness timed out ({last_error})", flush=True)
            return False
        try:
            if model_is_ready(min(5.0, remaining)):
                print(f"vLLM ready: {MODEL}", flush=True)
                return True
            last_error = "model not advertised"
        except Exception as error:  # noqa: BLE001 - connection/HTTP/JSON errors are retried
            # Exception strings may contain request details. Keep API keys and
            # tokenized URLs out of both installer output and the journal.
            last_error = type(error).__name__
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for the configured vLLM model.")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return 0 if wait_until_ready(args.timeout) else 1


if __name__ == "__main__":
    raise SystemExit(main())
