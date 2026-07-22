#!/usr/bin/env bash
#
# Remove the ohjime services installed by install.sh.
#
#   sudo ./deploy/uninstall.sh            # remove units, keep config + venvs
#   sudo ./deploy/uninstall.sh --purge    # also remove /etc/ohjime and the vLLM venv
#
# Model weights in ~/.cache/huggingface are never touched.
#
set -euo pipefail

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

[ "$(id -u)" -eq 0 ] || { echo "must run as root: sudo $0" >&2; exit 1; }

log() { printf '\033[1m==>\033[0m %s\n' "$*"; }

for unit in ohjime-summarizer.timer ohjime-summarizer.service ohjime-vllm.service; do
    if systemctl list-unit-files "$unit" >/dev/null 2>&1; then
        log "removing $unit"
        systemctl disable --now "$unit" >/dev/null 2>&1 || true
        rm -f "/etc/systemd/system/$unit"
    fi
done

systemctl daemon-reload
systemctl reset-failed >/dev/null 2>&1 || true

if [ "$PURGE" -eq 1 ]; then
    TARGET_USER="${SUDO_USER:-}"
    log "purging /etc/ohjime"
    rm -rf /etc/ohjime
    if [ -n "$TARGET_USER" ]; then
        USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
        if [ -d "$USER_HOME/.local/share/ohjime" ]; then
            log "purging $USER_HOME/.local/share/ohjime (vLLM venv)"
            rm -rf "$USER_HOME/.local/share/ohjime"
        fi
    fi
    log "model weights in ~/.cache/huggingface were left in place"
fi

log "done"
