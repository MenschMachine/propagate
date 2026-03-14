#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_FILE="$PROJECT_DIR/.smee.json"

CONFIG=""
PORT=8080
EVENTS="push,pull_request,issue_comment"
SECRET=""

usage() {
    echo "Usage: $0 --config <path> [--port <port>] [--events <comma-sep>] [--secret <secret>]"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --config) CONFIG="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --events) EVENTS="$2"; shift 2 ;;
        --secret) SECRET="$2"; shift 2 ;;
        *) usage ;;
    esac
done

[[ -z "$CONFIG" ]] && usage

# Check prerequisites
for cmd in gh npm python3; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: '$cmd' is required but not found." >&2
        exit 1
    fi
done

if ! gh auth status &>/dev/null; then
    echo "ERROR: 'gh' is not authenticated. Run 'gh auth login' first." >&2
    exit 1
fi

if [[ -f "$STATE_FILE" ]]; then
    echo "ERROR: $STATE_FILE already exists. Run smee-teardown.sh first." >&2
    exit 1
fi

# Generate a webhook secret if not provided
if [[ -z "$SECRET" ]]; then
    SECRET=$(openssl rand -hex 20)
fi

# Install smee-client if needed
if ! command -v smee &>/dev/null; then
    echo "Installing smee-client..."
    npm install -g smee-client
fi

# Create Smee channel
echo "Creating Smee channel..."
CHANNEL_URL=$(curl -Ls -o /dev/null -w '%{url_effective}' https://smee.io/new)
echo "Channel: $CHANNEL_URL"

# Get repos from config
REPOS=$(python3 "$SCRIPT_DIR/smee-parse-repos.py" --config "$CONFIG")
if [[ -z "$REPOS" ]]; then
    echo "ERROR: No GitHub repos found in config." >&2
    exit 1
fi

# Build events flags for gh api
IFS=',' read -ra EVENT_LIST <<< "$EVENTS"
EVENT_FLAGS=()
for evt in "${EVENT_LIST[@]}"; do
    EVENT_FLAGS+=(-f "events[]=$evt")
done

# Create webhooks
WEBHOOKS="[]"
while IFS= read -r repo; do
    echo "Creating webhook for $repo..."
    HOOK_ID=$(gh api "repos/$repo/hooks" --method POST \
        -f "config[url]=$CHANNEL_URL" \
        -f "config[content_type]=json" \
        -f "config[secret]=$SECRET" \
        -F "active=true" \
        "${EVENT_FLAGS[@]}" \
        -q '.id')
    echo "  Hook ID: $HOOK_ID"
    WEBHOOKS=$(echo "$WEBHOOKS" | jq --arg repo "$repo" --argjson id "$HOOK_ID" '. + [{"repo": $repo, "hook_id": $id}]')
done <<< "$REPOS"

# Write state file
jq -n \
    --arg channel_url "$CHANNEL_URL" \
    --argjson port "$PORT" \
    --arg secret "$SECRET" \
    --argjson webhooks "$WEBHOOKS" \
    '{channel_url: $channel_url, port: $port, secret: $secret, webhooks: $webhooks}' > "$STATE_FILE"

echo "Setup complete. State written to $STATE_FILE"
echo "Run scripts/smee-start.sh to begin forwarding."
