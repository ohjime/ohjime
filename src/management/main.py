"""Standalone runner for the vLLM-backed ADK agent (no `adk` CLI needed).

    uv run main.py            # scripted demo
    uv run main.py --chat     # interactive REPL

This wires the agent into an ADK Runner with an in-memory session and drives it
directly, which is the clearest way to see the vLLM -> LiteLLM -> ADK path work.
"""

import asyncio
import json
import sys
import urllib.error
import urllib.request

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from vllm_agent.agent import (
    VLLM_API_BASE,
    VLLM_API_KEY,
    VLLM_MODEL,
    build_agent,
)

APP_NAME = "adk_vllm_demo"
USER_ID = "demo-user"

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


async def ask(runner: Runner, session_id: str, prompt: str) -> None:
    """Send one user turn and print tool calls + the final response."""
    print(f"\n{BOLD}> {prompt}{RESET}")
    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=content
    ):
        for call in event.get_function_calls():
            print(f"  {DIM}[tool call] {call.name}({dict(call.args)}){RESET}")
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(part.text or "" for part in event.content.parts)
            if text.strip():
                print(text.strip())


def server_supports_tools() -> bool:
    """Quietly probe whether the vLLM server accepts OpenAI tool calls.

    ADK sends the agent's tools on *every* request, so if the server lacks
    `--enable-auto-tool-choice` even plain chat 400s. We check once up front and
    drop tools when unsupported, so the demo still runs end-to-end.
    """
    payload = {
        "model": VLLM_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [
            {
                "type": "function",
                "function": {"name": "noop", "description": "noop", "parameters": {"type": "object", "properties": {}}},
            }
        ],
        "tool_choice": "auto",
        "max_tokens": 1,
    }
    req = urllib.request.Request(
        VLLM_API_BASE.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {VLLM_API_KEY}"},
    )
    try:
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except urllib.error.HTTPError:
        return False
    except (urllib.error.URLError, OSError):
        return False  # unreachable server -> the Runner will report the real error


async def scripted_demo(runner: Runner, session_id: str, tools_enabled: bool) -> None:
    await ask(runner, session_id, "In one short sentence, what model and server are you running on?")
    if tools_enabled:
        await ask(
            runner,
            session_id,
            "Roll a 20-sided die, then tell me whether the number you rolled is prime.",
        )
    else:
        print(
            f"\n{DIM}[tools disabled] The vLLM server isn't running with "
            "--enable-auto-tool-choice --tool-call-parser hermes,\n"
            "so this run is chat-only. Start it with ./scripts/serve_vllm.sh to "
            f"enable the roll_dice / is_prime / get_current_time tools.{RESET}"
        )
        await ask(runner, session_id, "Give me one fun fact about large language models.")


async def interactive(runner: Runner, session_id: str) -> None:
    print(f"{DIM}Interactive chat. Type 'exit' or Ctrl-D to quit.{RESET}")
    while True:
        try:
            prompt = input(f"\n{BOLD}you>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if prompt.lower() in {"exit", "quit"}:
            break
        if prompt:
            await ask(runner, session_id, prompt)


async def main() -> None:
    print(f"{DIM}Agent -> LiteLLM -> vLLM  |  model={VLLM_MODEL}  base={VLLM_API_BASE}{RESET}")
    tools_enabled = server_supports_tools()

    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    runner = Runner(
        agent=build_agent(with_tools=tools_enabled),
        app_name=APP_NAME,
        session_service=session_service,
    )

    if "--chat" in sys.argv[1:]:
        await interactive(runner, session.id)
    else:
        await scripted_demo(runner, session.id, tools_enabled)


if __name__ == "__main__":
    asyncio.run(main())
