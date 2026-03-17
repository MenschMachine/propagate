# Deployment

Production deployment of Propagate on a Linux server using systemd and Caddy.

## Quick Start

```bash
# Fresh install
sudo bash deploy/install.sh --domain webhook.example.com

# Update (after pulling new code)
sudo bash deploy/install.sh --update
```

## What `install.sh` Does

**Fresh install:**

1. Installs system packages (python3, python3-venv, caddy)
2. Creates a `propagate` system user
3. Copies the project to `/opt/propagate`, creates venv, installs deps
4. Creates `.env` template at `/opt/propagate/.env` (you must fill in secrets)
5. Configures Caddy as reverse proxy with automatic HTTPS
6. Installs and starts three systemd services via `propagate.target`

**Update mode (`--update`):**

1. Syncs code to `/opt/propagate` (preserves `.env`, venv, state, context, config)
2. Reinstalls Python dependencies
3. Restarts all services

## Environment Variables

Edit `/opt/propagate/.env`:

| Variable | Description |
|----------|-------------|
| `GITHUB_WEBHOOK_SECRET` | GitHub webhook secret for signature verification |
| `GITHUB_TOKEN` | GitHub personal access token — used for repository cloning (injected into HTTPS URLs) and API calls |
| `CONFIG_PATH` | Path to propagate YAML config (relative to `/opt/propagate`) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `TELEGRAM_USERS` | Comma-separated Telegram user IDs allowed to use the bot |

## Architecture

Three independent systemd services grouped under a single target:

| Service | Description | Depends On |
|---------|-------------|------------|
| `propagate-serve` | Core ZeroMQ event loop | — |
| `propagate-webhook` | FastAPI webhook listener (127.0.0.1:8080) | propagate-serve |
| `propagate-telegram` | Telegram bot | propagate-serve |
| `propagate.target` | Groups all three | — |

Caddy handles external HTTPS traffic and reverse-proxies `/webhook*` to the webhook service.

## Common Operations

```bash
# View logs
journalctl -u propagate-serve -f
journalctl -u propagate-webhook -f
journalctl -u propagate-telegram -f

# View logs from all services
journalctl -u 'propagate-*' -f

# Restart all services
systemctl restart propagate.target

# Restart a single service
systemctl restart propagate-serve

# Stop all services
systemctl stop propagate.target

# Check status
systemctl status propagate-serve propagate-webhook propagate-telegram

# Update after pulling new code
sudo bash deploy/install.sh --update
```

## File Locations

| Path | Contents |
|------|----------|
| `/opt/propagate/` | Project root |
| `/opt/propagate/.env` | Environment variables (secrets) |
| `/opt/propagate/venv/` | Python virtual environment |
| `/opt/propagate/config/` | Configuration files |
| `/opt/propagate/.propagate-context/` | Context store |
| `/opt/propagate/.propagate-state-*.yaml` | Run state files |
| `/etc/caddy/Caddyfile` | Caddy reverse proxy config |
| `/etc/systemd/system/propagate-*.service` | systemd unit files |

## Caddy (HTTPS)

Caddy automatically provisions and renews TLS certificates via Let's Encrypt. No manual cert management needed. The Caddyfile is written by `install.sh` based on the `--domain` flag.

To change the domain, edit `/etc/caddy/Caddyfile` and run `systemctl restart caddy`.
