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

usage() {
    cat <<EOF
Usage: $(basename "$0") --config <path> [--config <path2> ...] [OPTIONS]

Start all propagate services with merged, labeled output.

Required:
  --config <path>       Path to a propagate YAML config (repeatable)

Options:
  --dev                 Also start smee (dev webhook forwarding)
  --port <port>         Port for the webhook server (default: 8080)
  --secret <value>      GitHub webhook secret
  --secret-env <var>    Env var containing the webhook secret (default: GITHUB_WEBHOOK_SECRET)
  --token <value>       Telegram bot token
  --token-env <var>     Env var containing the Telegram bot token (default: TELEGRAM_BOT_TOKEN)
  --allowed-users <ids> Comma-separated Telegram user IDs
  --resume [target]     Resume a previous run, optionally from a specific execution/task (e.g. suggest/wait-for-verdict)
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

if [[ ${#CONFIGS[@]} -eq 0 ]]; then
    echo "Error: --config is required" >&2
    echo "Run $(basename "$0") --help for usage" >&2
    exit 1
fi

# --- Child PIDs ---
PIDS=()

cleanup() {
    echo ""
    echo "Shutting down..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
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

# Webhook uses first config only (webhook is per-repo)
if [[ ${#CONFIGS[@]} -gt 1 ]]; then
    echo -e "${BLUE}[webhook ]${NC} Warning: webhook only uses first config (${CONFIGS[0]})"
fi
WEBHOOK_ARGS=(--config "${CONFIGS[0]}")
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
for cfg in "${CONFIGS[@]}"; do
    TELEGRAM_ARGS+=(--config "$cfg")
done
[[ -n "$TOKEN" ]] && TELEGRAM_ARGS+=(--token "$TOKEN")
[[ -n "$TOKEN_ENV" ]] && TELEGRAM_ARGS+=(--token-env "$TOKEN_ENV")
[[ -n "$ALLOWED_USERS" ]] && TELEGRAM_ARGS+=(--allowed-users "$ALLOWED_USERS")

if [[ "$DEBUG" == true ]]; then
    WEBHOOK_ARGS+=(--debug)
    TELEGRAM_ARGS+=(--debug)
fi

# --- Start services ---
echo -e "${GREEN}[serve   ]${NC} propagate serve ${SERVE_ARGS[*]}"
echo -e "${BLUE}[webhook ]${NC} propagate-webhook ${WEBHOOK_ARGS[*]}"
echo -e "${YELLOW}[telegram]${NC} propagate-telegram ${TELEGRAM_ARGS[*]}"

start_service "$GREEN" "serve" "$VENV/propagate" serve "${SERVE_ARGS[@]}"
start_service "$BLUE" "webhook" "$VENV/propagate-webhook" "${WEBHOOK_ARGS[@]}"
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
