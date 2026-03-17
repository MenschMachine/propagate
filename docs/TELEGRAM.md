# Telegram Bot Bridge

`propagate-telegram` is a Telegram bot that forwards messages as propagate signals via ZeroMQ. Send instructions from your phone, and they arrive as signal payload fields in the agent's prompt.

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

### `/signal <signal> [param:value ...]`

Send a signal to propagate with optional payload parameters.

**Key:value syntax** — each parameter is a `key:value` pair separated by spaces:

```
/signal deploy env:prod branch:main
```

This sends signal `deploy` with payload:

```json
{
  "env": "prod",
  "branch": "main",
  "sender": "michael"
}
```

**Quoted values** — use quotes for values containing spaces:

```
/signal deploy env:"prod and staging" branch:main
```

**Single-param shorthand** — when a signal has exactly one user-facing payload field (excluding `sender`), you can omit the field name:

```
/signal deploy
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

The signal name must match a signal defined in the propagate config. The `sender` field is automatically populated from your Telegram username. Payload fields are available in prompts as `:signal.<field>` (e.g. `:signal.instructions`, `:signal.sender`).

### `/logs [N]`

Show the last N lines of log output (default 20). Useful for checking what propagate is doing without SSH-ing into the server.

```
/logs
/logs 50
```

Output is truncated to Telegram's 4096 character message limit.

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

Send `/signal deploy Deploy to production.` in Telegram. The signal is delivered, the `deploy-app` execution starts, and the agent sees your instructions in its prompt.

---

## Auto-Reply on Events

When a signal is sent from Telegram, the bot automatically replies to the chat on key events. No extra configuration is needed — the bot subscribes to a ZMQ PUB socket that `propagate serve` publishes events on.

The serve process remains Telegram-agnostic. It publishes generic events with an opaque `metadata` dict that the bot uses to route replies back to the originating chat.

**Architecture:**

```
Telegram Bot                          Serve Process
┌──────────────┐    ZMQ PUSH/PULL    ┌──────────────────┐
│ /signal go   │ ──────────────────► │ receive signal   │
│              │                     │ run DAG          │
│              │    ZMQ PUB/SUB      │ capture logs     │
│ reply to chat│ ◄────────────────── │ publish event    │
└──────────────┘                     └──────────────────┘
```

### Event types

| Event | When | Message |
|-------|------|---------|
| `run_completed` | DAG finishes successfully | Run completed for signal 'X'. (+ last 3 log lines) |
| `run_failed` | DAG fails with an error | Run failed for signal 'X'. (+ last 3 log lines) |
| `waiting_for_signal` | System pauses to wait for a signal (sub-task or scheduler level) | Waiting for signal 'X' (execution 'Y'). |
| `pr_created` | A PR is opened by a git:pr hook | PR created for 'Y':\nhttps://... |
| `command_failed` | A command (e.g. /resume) fails | Command /resume failed: ... |

**Example `run_completed` event:**

```json
{
  "event": "run_completed",
  "signal_type": "deploy",
  "metadata": {"chat_id": "123", "message_id": "456"},
  "messages": ["Setting up...", "Running agent...", "Completed run for signal 'deploy'."]
}
```

**Example `waiting_for_signal` event:**

```json
{
  "event": "waiting_for_signal",
  "execution": "review-code",
  "signal": "review_done",
  "metadata": {"chat_id": "123", "message_id": "456"}
}
```

**Example `pr_created` event:**

```json
{
  "event": "pr_created",
  "execution": "deploy-app",
  "pr_url": "https://github.com/org/repo/pull/42",
  "metadata": {"chat_id": "123", "message_id": "456"}
}
```

The reply is sent to the chat that triggered the signal, as a reply to the original `/signal` message.

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
