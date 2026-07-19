#!/usr/bin/env bash
#
# Launch the local vLLM server with the flags this ADK demo needs.
#
# The key additions over a bare `vllm serve` are:
#   --enable-auto-tool-choice   enable OpenAI-style function calling
#   --tool-call-parser hermes   parser Qwen3 uses to emit tool calls
# Without these, the agent's tools (roll_dice / is_prime / get_current_time)
# cannot be invoked -- plain chat still works, but the demo's tool step fails.
#
# Usage:
#   ./scripts/serve_vllm.sh
#   VLLM_MODEL=Qwen/Qwen3-8B-AWQ PORT=8000 ./scripts/serve_vllm.sh
#
set -euo pipefail

VLLM_BIN="${VLLM_BIN:-/home/master/apps/vllm/bin/vllm}"
MODEL="${VLLM_MODEL:-Qwen/Qwen3-8B-AWQ}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

exec "$VLLM_BIN" serve "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.85 \
  --dtype float16 \
  --enforce-eager \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
  # Optional: route Qwen3 <think> traces into a separate `reasoning_content`
  # field instead of inline text by adding:
  #   --reasoning-parser qwen3
