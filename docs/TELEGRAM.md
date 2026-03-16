# Telegram Bot Bridge

`propagate-telegram` is a Telegram bot that forwards messages as propagate signals via ZeroMQ. Send instructions from your phone, and they arrive as `:signal.instructions` in the agent's prompt.

---

## Installation

```bash
pip install propagate[telegram]
```

---

## Usage

```bash
propagate-telegram --config config/propagate.yaml --token-env TELEGRAM_BOT_TOKEN --allowed-users 123456,789012
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | (required) | Path to the propagate YAML config |
| `--token` | (none) | Telegram bot token |
| `--token-env` | (none) | Environment variable name containing the bot token |
| `--allowed-users` | (required) | Comma-separated Telegram user IDs allowed to send commands |
| `--debug` | off | Enable debug-level logging |

The `--config` path must match the one used by `propagate serve` — it determines the ZeroMQ socket address.

---

## Bot Commands

### `/run <signal> [instructions]`

Send a signal to propagate with optional instructions.

```
/run deploy
Deploy branch main to staging.
Run smoke tests after.
```

This sends signal `deploy` with payload:

```json
{
  "instructions": "Deploy branch main to staging.\nRun smoke tests after.",
  "sender": "michael"
}
```

The signal name must match a signal defined in the propagate config. Instructions and sender are delivered as payload fields, available in prompts as `:signal.instructions` and `:signal.sender`.

### `/resume`

Resume a previously failed run. If a state file exists from a failed execution, propagate picks up where it left off — completed tasks are skipped, and it retries from the point of failure.

```
/resume
```

### `/signals`

List all signals defined in the propagate config.

### `/help`

Show available commands and configured signals.

---

## Config Example

Define a signal with an `instructions` payload field, then reference it in an execution:

```yaml
version: "6"
agent:
  command: "claude --prompt-file {prompt_file}"

repositories:
  app:
    path: ./

signals:
  deploy:
    payload:
      instructions:
        type: string
      sender:
        type: string

executions:
  deploy-app:
    repository: app
    signals:
      - signal: deploy
    sub_tasks:
      - id: execute
        prompt: ./prompts/deploy.md
```

```bash
# Terminal 1: start propagate server
propagate serve --config config/propagate.yaml

# Terminal 2: start telegram bot
propagate-telegram --config config/propagate.yaml --token-env TELEGRAM_BOT_TOKEN --allowed-users 123456
```

Send `/run deploy Deploy to production.` in Telegram. The signal is delivered, the `deploy-app` execution starts, and the agent sees your instructions in its prompt.

---

## Authentication

Only Telegram user IDs listed in `--allowed-users` can send commands. Messages from other users are silently ignored.

To find your Telegram user ID, message [@userinfobot](https://t.me/userinfobot) on Telegram.

---

## Creating a Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token
4. Store it in an environment variable: `export TELEGRAM_BOT_TOKEN="your-token"`
5. Start the bridge with `--token-env TELEGRAM_BOT_TOKEN`
