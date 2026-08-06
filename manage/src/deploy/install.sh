#!/usr/bin/env bash
#
# Install the ohjime Telegram summarizer stack on an Ubuntu machine.
#
#   git clone <repo> && cd ohjime/manage/src && sudo ./deploy/install.sh
#
# Sets up, idempotently (safe to re-run):
#   1. uv                      (per-user, if missing)
#   2. a vLLM venv on Python 3.12  (vLLM does not build on Ubuntu 26.04's 3.14)
#   3. the summarizer's own venv   (uv sync)
#   4. /etc/ohjime/*.env           (model + Telegram config; never overwritten)
#   5. /var/lib/ohjime             (private SQLite state directory)
#   6. ohjime-vllm.service         (the model server)
#   7. ohjime-telegram-collector.service  (continuous Telegram ingestion)
#   8. ohjime-summarizer.service + .timer (daily 10 PM processing)
#
# Options:
#   --no-timer      install the units but do not enable the daily timer
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
        --vllm-venv)
            [ "$#" -ge 2 ] && [ -n "$2" ] || {
                echo "--vllm-venv requires a directory" >&2
                exit 2
            }
            VLLM_VENV_OVERRIDE="$2"
            shift
            ;;
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

VLLM_VENV="${VLLM_VENV_OVERRIDE:-$USER_HOME/.local/share/ohjime/vllm}"

log "user=$TARGET_USER  home=$USER_HOME"
log "src =$SRC_DIR"

run_as_user() { sudo -u "$TARGET_USER" -H bash -c "$1"; }

# --- 1. Preflight -----------------------------------------------------------
log "preflight checks"

command -v systemctl >/dev/null || die "systemd not found; this installer targets Ubuntu/systemd"
command -v curl >/dev/null || die "curl not found; install it first: sudo apt install curl"

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
[ -x "$SRC_DIR/.venv/bin/python" ] || die "summarizer virtualenv was not created"
[ -f "$SRC_DIR/.env" ] || {
    log "creating $SRC_DIR/.env from .env.example"
    run_as_user "cp '$SRC_DIR/.env.example' '$SRC_DIR/.env'"
}

# --- 5. Config --------------------------------------------------------------
install -d -m 0755 /etc/ohjime
install -d -m 0700 -o "$TARGET_USER" -g "$USER_GROUP" /var/lib/ohjime
if [ -f /etc/ohjime/vllm.env ]; then
    log "/etc/ohjime/vllm.env exists — leaving it untouched"
else
    install -m 0644 "$DEPLOY_DIR/vllm.env.example" /etc/ohjime/vllm.env
    log "wrote /etc/ohjime/vllm.env"
fi

if [ -f /etc/ohjime/telegram.env ]; then
    log "/etc/ohjime/telegram.env exists — leaving its contents untouched"
else
    install -m 0600 "$DEPLOY_DIR/telegram.env.example" /etc/ohjime/telegram.env
    log "wrote /etc/ohjime/telegram.env"
fi
# The system manager reads EnvironmentFile before dropping privileges, so the
# bot token can and should remain readable only by root.
chown root:root /etc/ohjime/telegram.env
chmod 0600 /etc/ohjime/telegram.env

# Telegram cannot start with useful defaults. Only activate ingestion and the
# daily timer once a real token and numeric allow-list IDs have been supplied.
env_value() {
    local key="$1"
    sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" \
        /etc/ohjime/telegram.env | tail -1
}

TELEGRAM_CONFIG_READY=0
telegram_bot_token="$(env_value TELEGRAM_BOT_TOKEN)"
allowed_user_id="$(env_value ALLOWED_USER_ID)"
allowed_chat_id="$(env_value ALLOWED_CHAT_ID)"
thought_thread_id="$(env_value THOUGHT_THREAD_ID)"
action_thread_id="$(env_value ACTION_THREAD_ID)"
max_batch_bytes="$(env_value MAX_BATCH_BYTES)"
max_batch_bytes_valid=0
if [[ -z "$max_batch_bytes" ]]; then
    max_batch_bytes_valid=1
elif [[ "$max_batch_bytes" =~ ^[1-9][0-9]*$ ]] &&
    (( 10#$max_batch_bytes >= 512 ))
then
    max_batch_bytes_valid=1
fi

if [[ "$telegram_bot_token" != *replace* ]] &&
    [[ "$telegram_bot_token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] &&
    [[ "$allowed_user_id" =~ ^[0-9]+$ ]] &&
    [[ "$allowed_chat_id" =~ ^-?[0-9]+$ ]] &&
    [[ -z "$thought_thread_id" || "$thought_thread_id" =~ ^[0-9]+$ ]] &&
    [[ -z "$action_thread_id" || "$action_thread_id" =~ ^[0-9]+$ ]] &&
    [[ "$max_batch_bytes_valid" -eq 1 ]]
then
    TELEGRAM_CONFIG_READY=1
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
        -e "s|@@VLLM_BIN@@|$VLLM_BIN|g" \
        -e "s|@@UV_BIN@@|$UV_BIN|g" \
        "$1" > "$2"
    chmod 0644 "$2"
}

log "installing systemd units"
render "$DEPLOY_DIR/ohjime-vllm.service"       /etc/systemd/system/ohjime-vllm.service
render "$DEPLOY_DIR/ohjime-telegram-collector.service" \
    /etc/systemd/system/ohjime-telegram-collector.service
render "$DEPLOY_DIR/ohjime-summarizer.service" /etc/systemd/system/ohjime-summarizer.service
render "$DEPLOY_DIR/ohjime-summarizer.timer"   /etc/systemd/system/ohjime-summarizer.timer
systemctl daemon-reload

# --- 8. Start ---------------------------------------------------------------
if [ "$START_SERVER" -eq 1 ]; then
    log "enabling + starting ohjime-vllm (first run may download ~5.5 GB)"
    systemctl enable ohjime-vllm.service
    systemctl restart ohjime-vllm.service

    log "waiting for the model endpoint configured in $SRC_DIR/.env"
    if ! run_as_user \
        "'$SRC_DIR/.venv/bin/python' '$SRC_DIR/wait_for_vllm.py' --timeout 600"
    then
        warn "server not up yet; watch it with:  journalctl -u ohjime-vllm -f"
    fi
else
    systemctl enable ohjime-vllm.service
    log "installed but not started (--no-start)"
fi

if [ "$TELEGRAM_CONFIG_READY" -eq 1 ]; then
    systemctl enable ohjime-telegram-collector.service
    systemctl restart ohjime-telegram-collector.service
    log "Telegram collector enabled + started"

    if [ "$ENABLE_TIMER" -eq 1 ]; then
        systemctl enable ohjime-summarizer.timer
        systemctl restart ohjime-summarizer.timer
        log "daily 10 PM summarizer timer enabled"
    else
        systemctl disable --now ohjime-summarizer.timer >/dev/null 2>&1 || true
        log "timer left disabled (--no-timer)"
    fi
else
    systemctl disable --now ohjime-telegram-collector.service \
        ohjime-summarizer.timer >/dev/null 2>&1 || true
    warn "Telegram credentials are still placeholders; collector and timer are disabled"
    warn "edit /etc/ohjime/telegram.env, then rerun: sudo ./deploy/install.sh"
fi

cat <<EOF

$(printf '\033[32mInstalled.\033[0m')

  model server   systemctl status ohjime-vllm
  collector      systemctl status ohjime-telegram-collector
  run summarizer sudo systemctl start ohjime-summarizer
  collector logs journalctl -u ohjime-telegram-collector -f
  processor logs journalctl -u ohjime-summarizer -f
  schedule       systemctl list-timers ohjime-summarizer.timer
  config         /etc/ohjime/{vllm,telegram}.env
  database       /var/lib/ohjime/messages.db
  uninstall      sudo ./deploy/uninstall.sh
EOF
