#!/usr/bin/env bash
#
# Durably enable OpenAI-style tool calling on the systemd-managed vLLM service.
#
# It adds the required flags to VLLM_EXTRA in /etc/vllm/vllm.env and restarts the
# service, so tool calling stays on across reboots and service restarts. Safe to
# run more than once (idempotent) and it backs up the env file first.
#
# Run once, as root:
#   sudo /home/master/apps/adk-demo/scripts/enable_service_tools.sh
#
set -euo pipefail

ENVFILE=/etc/vllm/vllm.env
FLAGS="--enable-auto-tool-choice --tool-call-parser hermes"

if [ "$(id -u)" -ne 0 ]; then
    echo "This edits $ENVFILE and restarts the vllm service; run with sudo:" >&2
    echo "  sudo $0" >&2
    exit 1
fi

[ -f "$ENVFILE" ] || { echo "error: $ENVFILE not found" >&2; exit 1; }

# Back up once (don't clobber an existing backup).
cp -n "$ENVFILE" "$ENVFILE.bak" || true

if grep -q '^VLLM_EXTRA=' "$ENVFILE"; then
    if grep '^VLLM_EXTRA=' "$ENVFILE" | grep -q 'enable-auto-tool-choice'; then
        echo "tool flags already present in VLLM_EXTRA — nothing to change"
    else
        sed -i -E "s#^(VLLM_EXTRA=.*)#\1 ${FLAGS}#" "$ENVFILE"
        echo "added tool flags to VLLM_EXTRA"
    fi
else
    printf '\nVLLM_EXTRA=%s\n' "$FLAGS" >> "$ENVFILE"
    echo "created VLLM_EXTRA with tool flags"
fi

echo "--- /etc/vllm/vllm.env ---"
grep -E '^(VLLM_MODEL|VLLM_EXTRA)=' "$ENVFILE"
echo "--------------------------"

echo "restarting vllm service (model reload can take a minute)..."
systemctl restart vllm
sleep 2
systemctl --no-pager --lines=0 status vllm | head -4
echo "done. Verify with:  cd /home/master/apps/adk-demo && uv run check_vllm.py"
