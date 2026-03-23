#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$PROJECT_DIR/venv/bin"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- Defaults ---
CONFIGS=()
DEV=false
PORT=""
SECRET=""
SECRET_ENV="GITHUB_WEBHOOK_SECRET"
TOKEN=""
TOKEN_ENV="TELEGRAM_BOT_TOKEN"
ALLOWED_USERS=""
DEBUG=false
RESUME=""
WORKER_STDOUT_LOG=""
SKIPS=()

usage() {
    cat <<EOF
Usage: $(basename "$0") [--config <path> ...] [OPTIONS]

Start all propagate services with merged, labeled output.

Options:
  --config <path>       Path to a propagate YAML config (repeatable, optional)
  --dev                 Also start smee (dev webhook forwarding)
  --port <port>         Port for the webhook server (default: 8080)
  --secret <value>      GitHub webhook secret
  --secret-env <var>    Env var containing the webhook secret (default: GITHUB_WEBHOOK_SECRET)
  --token <value>       Telegram bot token
  --token-env <var>     Env var containing the Telegram bot token (default: TELEGRAM_BOT_TOKEN)
  --allowed-users <ids> Comma-separated Telegram user IDs
  --resume [target]     Resume a previous run, optionally from a specific execution/task (e.g. suggest/wait-for-verdict)
  --skip <target>       Skip an execution or task (execution_name or execution_name/task_id, repeatable)
  --worker-stdout-log <path>
                        Write worker stdout transcripts to this file
  --debug               Enable debug logging on all services
  --help                Show this help
EOF
    exit 0
}

# --- Parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)     CONFIGS+=("$2"); shift 2 ;;
        --dev)        DEV=true; shift ;;
        --port)       PORT="$2"; shift 2 ;;
        --secret)     SECRET="$2"; shift 2 ;;
        --secret-env) SECRET_ENV="$2"; shift 2 ;;
        --token)      TOKEN="$2"; shift 2 ;;
        --token-env)  TOKEN_ENV="$2"; shift 2 ;;
        --allowed-users) ALLOWED_USERS="$2"; shift 2 ;;
        --skip)           SKIPS+=("$2"); shift 2 ;;
        --worker-stdout-log) WORKER_STDOUT_LOG="$2"; shift 2 ;;
        --resume)
            if [[ $# -ge 2 && ! "$2" =~ ^-- ]]; then
                RESUME="$2"; shift 2
            else
                RESUME="__bare__"; shift
            fi
            ;;
        --debug)      DEBUG=true; shift ;;
        --help|-h)    usage ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# --- Child PIDs ---
PIDS=()

_kill_tree() {
    local pid=$1
    # Find and kill children first (depth-first).
    for child in $(pgrep -P "$pid" 2>/dev/null); do
        _kill_tree "$child"
    done
    kill "$pid" 2>/dev/null || true
}

cleanup() {
    echo ""
    echo "Shutting down..."
    for pid in "${PIDS[@]}"; do
        _kill_tree "$pid"
    done
    sleep 1
    # Force-kill any stragglers.
    for pid in "${PIDS[@]}"; do
        kill -9 "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo "All services stopped."
    exit 0
}
trap cleanup SIGINT SIGTERM

# --- Helpers ---
prefix_output() {
    local color="$1"
    local label="$2"
    local width=8
    awk -v c="$color" -v l="$label" -v nc="$NC" -v w="$width" \
        'BEGIN { pad = sprintf("%-*s", w, l) } {print c "[" pad "]" nc " " $0; fflush()}'
}

start_service() {
    local color="$1"
    local label="$2"
    shift 2
    "$@" 2>&1 | prefix_output "$color" "$label" &
    PIDS+=($!)
}

# --- Build command args ---
SERVE_ARGS=()
for cfg in "${CONFIGS[@]}"; do
    SERVE_ARGS+=(--config "$cfg")
done
if [[ "$RESUME" == "__bare__" ]]; then
    SERVE_ARGS+=(--resume)
elif [[ -n "$RESUME" ]]; then
    SERVE_ARGS+=(--resume "$RESUME")
fi
if [[ -n "$WORKER_STDOUT_LOG" ]]; then
    SERVE_ARGS+=(--worker-stdout-log "$WORKER_STDOUT_LOG")
fi
for skip_val in "${SKIPS[@]}"; do
    SERVE_ARGS+=(--skip "$skip_val")
done

# Webhook connects to coordinator. No --config or --project needed —
# coordinator routes signals by matching repository in the payload.
WEBHOOK_ARGS=()
[[ -n "$PORT" ]] && WEBHOOK_ARGS+=(--port "$PORT")
if [[ "$DEV" == true ]]; then
    # Skip signature verification in dev mode — smee re-serialises the body,
    # which breaks HMAC validation.
    echo -e "${BLUE}[webhook ]${NC} Dev mode: skipping webhook signature verification"
elif [[ -n "$SECRET" ]]; then
    WEBHOOK_ARGS+=(--secret "$SECRET")
elif [[ -n "$SECRET_ENV" ]]; then
    WEBHOOK_ARGS+=(--secret-env "$SECRET_ENV")
fi

TELEGRAM_ARGS=()
# No --config: telegram connects to the coordinator automatically.
[[ -n "$TOKEN" ]] && TELEGRAM_ARGS+=(--token "$TOKEN")
[[ -n "$TOKEN_ENV" ]] && TELEGRAM_ARGS+=(--token-env "$TOKEN_ENV")
[[ -n "$ALLOWED_USERS" ]] && TELEGRAM_ARGS+=(--allowed-users "$ALLOWED_USERS")

if [[ "$DEBUG" == true ]]; then
    WEBHOOK_ARGS+=(--debug)
    TELEGRAM_ARGS+=(--debug)
fi

# --- Start services ---
echo -e "${GREEN}[serve   ]${NC} propagate serve ${SERVE_ARGS[*]}"
start_service "$GREEN" "serve" "$VENV/propagate" serve "${SERVE_ARGS[@]}"

echo -e "${BLUE}[webhook ]${NC} propagate-webhook ${WEBHOOK_ARGS[*]}"
start_service "$BLUE" "webhook" "$VENV/propagate-webhook" "${WEBHOOK_ARGS[@]}"

echo -e "${YELLOW}[telegram]${NC} propagate-telegram ${TELEGRAM_ARGS[*]}"
start_service "$YELLOW" "telegram" "$VENV/propagate-telegram" "${TELEGRAM_ARGS[@]}"

if [[ "$DEV" == true ]]; then
    echo -e "${RED}[smee    ]${NC} smee (dev forwarding)"
    start_service "$RED" "smee" bash "$SCRIPT_DIR/smee-start.sh"
fi

echo ""
echo "All services started. Press Ctrl+C to stop."
echo ""

# Wait for any child to exit
wait
