#!/usr/bin/env bash
# Ensures a pdfdancer-api Docker container is running for the given PR image.
# Reuses an existing container if one is already running with the same image.
# Prints the base URL (e.g. http://localhost:12345) to stdout on success.
#
# Usage: start-api-server.sh <api-pr-number>

set -euo pipefail

PR_NUMBER="${1:?Usage: start-api-server.sh <api-pr-number>}"
IMAGE="ghcr.io/menschmachine/pdfdancer-api:pr-${PR_NUMBER}"

# Pull the image to check if a newer version is available.
docker pull "$IMAGE" >&2

# Get the current image ID for this tag.
CURRENT_IMAGE_ID=$(docker images --no-trunc -q "$IMAGE" | head -1)

# Check if a container is already running with this exact image.
EXISTING=$(docker ps --filter "ancestor=${IMAGE}" --format '{{.ID}}' | head -1)
if [[ -n "$EXISTING" ]]; then
  # Verify the running container is using the current image.
  RUNNING_IMAGE_ID=$(docker inspect --format '{{.Image}}' "$EXISTING")
  if [[ "$RUNNING_IMAGE_ID" == "$CURRENT_IMAGE_ID" ]]; then
    PORT=$(docker port "$EXISTING" 9090 | head -1 | cut -d: -f2)
    echo "http://localhost:${PORT}"
    exit 0
  fi
  # Image was updated, stop and remove the old container so we can recreate it.
  docker stop "$EXISTING" >/dev/null 2>&1 || true
  docker rm "$EXISTING" >/dev/null 2>&1 || true
fi

# Start a new container on a random free port.
CONTAINER_ID=$(docker run -d \
    -e PDFDANCER_API_KEY_ENCRYPTION_SECRET="$(openssl rand -hex 16)" \
    -e FONTS_DIR=/tmp/fonts \
    -e METRICS_ENABLED=false \
    -e SWAGGER_ENABLED=true \
    -v /tmp/fonts:/home/app/fonts \
    -p 0:8080 \
    "$IMAGE")

PORT=$(docker port "$CONTAINER_ID" 9090 | head -1 | cut -d: -f2)
BASE_URL="http://localhost:${PORT}"

# Wait for the server to become ready.
for i in $(seq 1 30); do
  if curl -sf "${BASE_URL}/ping" >/dev/null 2>&1; then
    echo "$BASE_URL"
    exit 0
  fi
  sleep 1
done

echo "Server failed to respond to /ping after 30s" >&2
docker logs "$CONTAINER_ID" >&2
docker stop "$CONTAINER_ID" >/dev/null 2>&1 || true
exit 1
