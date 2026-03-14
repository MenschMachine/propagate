#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_FILE="$PROJECT_DIR/.smee.json"

if [[ ! -f "$STATE_FILE" ]]; then
    echo "ERROR: $STATE_FILE not found. Nothing to tear down." >&2
    exit 1
fi

WEBHOOKS=$(jq -c '.webhooks[]' "$STATE_FILE")

while IFS= read -r entry; do
    repo=$(echo "$entry" | jq -r '.repo')
    hook_id=$(echo "$entry" | jq -r '.hook_id')
    echo "Deleting webhook $hook_id from $repo..."
    if gh api "repos/$repo/hooks/$hook_id" --method DELETE 2>/dev/null; then
        echo "  Deleted."
    else
        echo "  Already gone or failed (ignored)."
    fi
done <<< "$WEBHOOKS"

rm "$STATE_FILE"
echo "Teardown complete."
