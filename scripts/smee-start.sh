#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_FILE="$PROJECT_DIR/.smee.json"

if [[ ! -f "$STATE_FILE" ]]; then
    echo "ERROR: $STATE_FILE not found. Run propagate-setup.py first." >&2
    exit 1
fi

CHANNEL_URL=$(jq -r '.channel_url' "$STATE_FILE")
PORT=$(jq -r '.port' "$STATE_FILE")

cleanup() {
    echo "Stopping smee client..."
    exit 0
}
trap cleanup SIGINT SIGTERM

echo "Forwarding $CHANNEL_URL -> localhost:$PORT/webhook"
smee --url "$CHANNEL_URL" --port "$PORT" --path /webhook
