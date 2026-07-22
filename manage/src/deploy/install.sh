#!/usr/bin/env bash
#
# Install the ohjime dump-summarizer stack on an Ubuntu machine.
#
#   git clone <repo> && cd ohjime/manage/src && sudo ./deploy/install.sh
#
# Sets up, idempotently (safe to re-run):
#   1. uv                      (per-user, if missing)
#   2. a vLLM venv on Python 3.12  (vLLM does not build on Ubuntu 26.04's 3.14)
#   3. the summarizer's own venv   (uv sync)
#   4. /etc/ohjime/vllm.env        (model server config; never overwritten)
#   5. ohjime-vllm.service         (the model server)
#   6. ohjime-summarizer.service + .timer  (hourly summarize run)
#
# Options:
#   --no-timer      install the units but do not enable the hourly timer
#   --no-start      install everything but do not start the model server
#   --vllm-venv D   use/create the vLLM venv at directory D
#
set -euo pipefail

VLLM_VERSION="${VLLM_VERSION:-0.25.0}"   # proven on Turing (SM 7.5) with Qwen3-8B-AWQ
PYTHON_VERSION="${PYTHON_VERSION:-3.12}" # vLLM has no 3.13/3.14 wheels yet
ENABLE_TIMER=1
START_SERVER=1
VLLM_VENV_OVERRIDE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --no-timer)   ENABLE_TIMER=0 ;;
        --no-start)   START_SERVER=0 ;;
        --vllm-venv)  VLLM_VENV_OVERRIDE="$2"; shift ;;
        -h|--help)    sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

log()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarn:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- 0. Context -------------------------------------------------------------
[ "$(id -u)" -eq 0 ] || die "must run as root:  sudo $0"

# Services run as the human who invoked sudo, not root: the GPU, the HF cache
# and the repo checkout all live in that user's world.
TARGET_USER="${SUDO_USER:-}"
[ -n "$TARGET_USER" ] && [ "$TARGET_USER" != "root" ] || \
    die "run via sudo from your normal user account (not a root login), so the
       services can run as that user:  sudo ./deploy/install.sh"

USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
USER_GROUP="$(id -gn "$TARGET_USER")"
[ -d "$USER_HOME" ] || die "home directory for $TARGET_USER not found"

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$SRC_DIR/deploy"
REPO_ROOT="$(git -C "$SRC_DIR" rev-parse --show-toplevel 2>/dev/null || echo "")"
[ -n "$REPO_ROOT" ] || die "$SRC_DIR is not inside a git clone (summarize.py needs git pull)"

VLLM_VENV="${VLLM_VENV_OVERRIDE:-$USER_HOME/.local/share/ohjime/vllm}"

log "user=$TARGET_USER  home=$USER_HOME"
log "repo=$REPO_ROOT"
log "src =$SRC_DIR"

run_as_user() { sudo -u "$TARGET_USER" -H bash -c "$1"; }

# --- 1. Preflight -----------------------------------------------------------
log "preflight checks"

command -v systemctl >/dev/null || die "systemd not found; this installer targets Ubuntu/systemd"

if command -v nvidia-smi >/dev/null 2>&1; then
    gpu_info="$(nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader | head -1)"
    log "  GPU: $gpu_info"
    cap="$(echo "$gpu_info" | awk -F', ' '{print $3}')"
    case "$cap" in
        7.0|7.2|7.5)
            log "  Turing/Volta detected — float16 + eager mode are set in vllm.env" ;;
        "") warn "  could not read compute capability" ;;
    esac
else
    die "nvidia-smi not found: install the NVIDIA driver first, e.g.
       sudo ubuntu-drivers install"
fi

avail_gb="$(df -BG --output=avail / | tail -1 | tr -dc '0-9')"
if [ "${avail_gb:-0}" -lt 25 ]; then
    warn "only ${avail_gb}G free on / — vLLM (~10G) plus weights (~6G) may not fit."
    warn "If this is a fresh Ubuntu LVM install, the root LV is often capped at"
    warn "100G while the disk is far larger. Check with:  lsblk ; then grow it:"
    warn "  sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv"
    warn "  sudo resize2fs /dev/ubuntu-vg/ubuntu-lv"
fi

# --- 2. uv ------------------------------------------------------------------
UV_BIN="$USER_HOME/.local/bin/uv"
if [ ! -x "$UV_BIN" ]; then
    if command -v uv >/dev/null 2>&1; then
        UV_BIN="$(command -v uv)"
    else
        log "installing uv for $TARGET_USER"
        run_as_user "curl -LsSf https://astral.sh/uv/install.sh | sh" >/dev/null
        [ -x "$UV_BIN" ] || die "uv installation failed"
    fi
fi
log "uv: $UV_BIN ($("$UV_BIN" --version 2>/dev/null || echo '?'))"

# --- 3. vLLM venv -----------------------------------------------------------
# Reuse an existing vLLM install if one is already on the box (avoids a ~10 GB
# reinstall); otherwise create a Python 3.12 venv and install the pinned vLLM.
VLLM_BIN=""
for candidate in "$VLLM_VENV/bin/vllm" "$USER_HOME/apps/vllm/bin/vllm"; do
    if [ -x "$candidate" ]; then
        VLLM_BIN="$candidate"
        log "reusing existing vLLM: $VLLM_BIN"
        break
    fi
done

if [ -z "$VLLM_BIN" ]; then
    log "creating vLLM venv at $VLLM_VENV (Python $PYTHON_VERSION)"
    run_as_user "mkdir -p '$(dirname "$VLLM_VENV")'"
    run_as_user "'$UV_BIN' venv --python '$PYTHON_VERSION' '$VLLM_VENV'"
    log "installing vllm==$VLLM_VERSION (large download, several minutes)"
    run_as_user "VIRTUAL_ENV='$VLLM_VENV' '$UV_BIN' pip install 'vllm==$VLLM_VERSION'"
    VLLM_BIN="$VLLM_VENV/bin/vllm"
    [ -x "$VLLM_BIN" ] || die "vLLM install failed"
fi

# --- 4. Summarizer deps -----------------------------------------------------
log "installing summarizer dependencies (uv sync)"
run_as_user "cd '$SRC_DIR' && '$UV_BIN' sync"
[ -f "$SRC_DIR/.env" ] || {
    log "creating $SRC_DIR/.env from .env.example"
    run_as_user "cp '$SRC_DIR/.env.example' '$SRC_DIR/.env'"
}

# --- 5. Config --------------------------------------------------------------
install -d -m 0755 /etc/ohjime
if [ -f /etc/ohjime/vllm.env ]; then
    log "/etc/ohjime/vllm.env exists — leaving it untouched"
else
    install -m 0644 "$DEPLOY_DIR/vllm.env.example" /etc/ohjime/vllm.env
    log "wrote /etc/ohjime/vllm.env"
fi

# --- 6. Legacy service ------------------------------------------------------
# A hand-rolled vllm.service would fight this one for port 8000 and the GPU.
if [ -f /etc/systemd/system/vllm.service ]; then
    warn "found a pre-existing vllm.service; disabling it (it conflicts on the"
    warn "GPU and port). Re-enable with: sudo systemctl enable --now vllm"
    systemctl disable --now vllm.service >/dev/null 2>&1 || true
fi

# --- 7. Units ---------------------------------------------------------------
render() {
    sed -e "s|@@USER@@|$TARGET_USER|g" \
        -e "s|@@GROUP@@|$USER_GROUP|g" \
        -e "s|@@HOME@@|$USER_HOME|g" \
        -e "s|@@SRC_DIR@@|$SRC_DIR|g" \
        -e "s|@@REPO_ROOT@@|$REPO_ROOT|g" \
        -e "s|@@VLLM_BIN@@|$VLLM_BIN|g" \
        -e "s|@@UV_BIN@@|$UV_BIN|g" \
        "$1" > "$2"
    chmod 0644 "$2"
}

log "installing systemd units"
render "$DEPLOY_DIR/ohjime-vllm.service"       /etc/systemd/system/ohjime-vllm.service
render "$DEPLOY_DIR/ohjime-summarizer.service" /etc/systemd/system/ohjime-summarizer.service
render "$DEPLOY_DIR/ohjime-summarizer.timer"   /etc/systemd/system/ohjime-summarizer.timer
systemctl daemon-reload

# --- 8. Start ---------------------------------------------------------------
if [ "$START_SERVER" -eq 1 ]; then
    log "enabling + starting ohjime-vllm (first run may download ~5.5 GB)"
    systemctl enable --now ohjime-vllm.service

    port="$(. /etc/ohjime/vllm.env; echo "${VLLM_PORT:-8000}")"
    printf '    waiting for the model server on :%s ' "$port"
    for _ in $(seq 1 120); do
        if curl -sf --max-time 2 "http://localhost:$port/v1/models" >/dev/null 2>&1; then
            printf ' ready\n'
            break
        fi
        printf '.'
        sleep 5
    done
    curl -sf --max-time 2 "http://localhost:$port/v1/models" >/dev/null 2>&1 || {
        printf '\n'
        warn "server not up yet; watch it with:  journalctl -u ohjime-vllm -f"
    }
else
    systemctl enable ohjime-vllm.service
    log "installed but not started (--no-start)"
fi

if [ "$ENABLE_TIMER" -eq 1 ]; then
    systemctl enable --now ohjime-summarizer.timer
    log "hourly summarizer timer enabled"
else
    log "timer left disabled (--no-timer)"
fi

cat <<EOF

$(printf '\033[32mInstalled.\033[0m')

  model server   systemctl status ohjime-vllm
  run summarizer sudo systemctl start ohjime-summarizer
  logs           journalctl -u ohjime-summarizer -f
  schedule       systemctl list-timers ohjime-summarizer.timer
  config         /etc/ohjime/vllm.env
  uninstall      sudo ./deploy/uninstall.sh
EOF
