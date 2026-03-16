#!/usr/bin/env bash
set -euo pipefail

# --- Constants ---
INSTALL_DIR="/opt/propagate"
SERVICE_USER="propagate"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

# --- Defaults ---
DOMAIN=""
UPDATE=false

# --- Colors ---
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: sudo bash $(basename "$0") [OPTIONS]

Install or update Propagate services on a Linux server.

Options:
  --domain <domain>   Domain for Caddy reverse proxy (e.g., webhook.example.com)
  --update            Update mode: pull latest code, reinstall deps, restart services
  --help              Show this help

Examples:
  Fresh install:  sudo bash deploy/install.sh --domain webhook.example.com
  Update:         sudo bash deploy/install.sh --update
EOF
    exit 0
}

log() { echo -e "${GREEN}[install]${NC} $*"; }
err() { echo -e "${RED}[error]${NC} $*" >&2; }

# --- Parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)  DOMAIN="$2"; shift 2 ;;
        --update)  UPDATE=true; shift ;;
        --help|-h) usage ;;
        *) err "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Root check ---
if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root (use sudo)"
    exit 1
fi

# =============================================================================
# UPDATE MODE
# =============================================================================
if [[ "$UPDATE" == true ]]; then
    log "Update mode — syncing code and restarting services"

    if [[ ! -d "$INSTALL_DIR" ]]; then
        err "$INSTALL_DIR does not exist. Run a fresh install first."
        exit 1
    fi

    # Sync project files (exclude .env, venv, state files, context)
    log "Syncing project files..."
    rsync -a --delete \
        --exclude='.env' \
        --exclude='venv/' \
        --exclude='.propagate-context/' \
        --exclude='.propagate-state-*' \
        --exclude='.git/' \
        --exclude='config/' \
        "$PROJECT_DIR/" "$INSTALL_DIR/"

    # Reinstall dependencies
    log "Reinstalling dependencies..."
    "$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR[webhook,telegram]" --quiet

    # Restart services
    log "Restarting services..."
    systemctl daemon-reload
    systemctl restart propagate.target

    log "Update complete"
    systemctl --no-pager status propagate-serve propagate-webhook propagate-telegram || true
    exit 0
fi

# =============================================================================
# FRESH INSTALL
# =============================================================================

# --- Validate args ---
if [[ -z "$DOMAIN" ]]; then
    err "--domain is required for fresh install"
    echo "Run $(basename "$0") --help for usage" >&2
    exit 1
fi

# --- Step 1: System packages ---
log "Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git rsync

# Install Caddy
if ! command -v caddy &>/dev/null; then
    log "Installing Caddy..."
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y -qq caddy
fi

# --- Step 2: Create system user ---
if ! id "$SERVICE_USER" &>/dev/null; then
    log "Creating system user '$SERVICE_USER'..."
    useradd --system --shell /usr/sbin/nologin --home-dir "$INSTALL_DIR" "$SERVICE_USER"
fi

# --- Step 3: Set up /opt/propagate ---
log "Setting up $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# Sync project files
rsync -a --delete \
    --exclude='.env' \
    --exclude='venv/' \
    --exclude='.propagate-context/' \
    --exclude='.propagate-state-*' \
    --exclude='.git/' \
    "$PROJECT_DIR/" "$INSTALL_DIR/"

# Create venv if it doesn't exist
if [[ ! -d "$INSTALL_DIR/venv" ]]; then
    log "Creating virtual environment..."
    python3 -m venv "$INSTALL_DIR/venv"
fi

# Install dependencies
log "Installing Python dependencies..."
"$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR[webhook,telegram]" --quiet

# --- Step 4: Environment file ---
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    log "Creating .env from template..."
    cat > "$INSTALL_DIR/.env" <<'ENVEOF'
# Propagate environment configuration
# Edit these values before starting services

# GitHub
GITHUB_WEBHOOK_SECRET=
GITHUB_TOKEN=

# Config path (relative to /opt/propagate)
CONFIG_PATH=config/propagate.yaml

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_USERS=
ENVEOF
    echo ""
    echo "=========================================="
    echo "  IMPORTANT: Edit $INSTALL_DIR/.env"
    echo "  Fill in your secrets before starting."
    echo "=========================================="
    echo ""
fi

# Fix ownership
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# --- Step 5: Caddy reverse proxy ---
log "Configuring Caddy for domain: $DOMAIN"
cat > /etc/caddy/Caddyfile <<CADDYEOF
${DOMAIN} {
    reverse_proxy /webhook* 127.0.0.1:8080
}
CADDYEOF
systemctl enable caddy
systemctl restart caddy

# --- Step 6: Install systemd units ---
log "Installing systemd service units..."
cp "$DEPLOY_DIR/propagate-serve.service" "$SYSTEMD_DIR/"
cp "$DEPLOY_DIR/propagate-webhook.service" "$SYSTEMD_DIR/"
cp "$DEPLOY_DIR/propagate-telegram.service" "$SYSTEMD_DIR/"
cp "$DEPLOY_DIR/propagate.target" "$SYSTEMD_DIR/"

systemctl daemon-reload
systemctl enable propagate.target
systemctl start propagate.target

# --- Step 7: Status summary ---
echo ""
log "Installation complete"
echo ""
echo "Services:"
systemctl --no-pager status propagate-serve propagate-webhook propagate-telegram 2>&1 | head -30 || true
echo ""
echo "Useful commands:"
echo "  journalctl -u propagate-serve -f        # Follow serve logs"
echo "  journalctl -u propagate-webhook -f      # Follow webhook logs"
echo "  journalctl -u propagate-telegram -f     # Follow telegram logs"
echo "  systemctl restart propagate.target       # Restart all services"
echo "  systemctl stop propagate.target          # Stop all services"
echo "  sudo bash deploy/install.sh --update     # Update code & restart"
