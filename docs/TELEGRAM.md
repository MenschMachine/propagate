# Telegram Bot Bridge

`propagate-telegram` is a Telegram bot that forwards messages as propagate signals via ZeroMQ. Send instructions from your phone, and they arrive as signal payload fields in the agent's prompt.

---

## Installation

```bash
pip install propagate[telegram]
```

---

## Usage

### Coordinator mode (recommended)

When running without `--config`, the bot connects to the coordinator and discovers projects automatically:

```bash
propagate-telegram --token-env TELEGRAM_BOT_TOKEN --allowed-users 123456,789012
```

This requires a running `propagate serve` instance. The bot sends a `list` command to the coordinator at startup to discover available projects and their signals.

### Legacy mode

Connect directly to specific config sockets (bypasses coordinator):

```bash
propagate-telegram --config config/propagate.yaml --token-env TELEGRAM_BOT_TOKEN --allowed-users 123456,789012
```

The `--config` path must match the one used by `propagate serve`. Pass multiple `--config` flags to connect to multiple serve instances.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | (none) | Path to a propagate YAML config (repeatable). If omitted, connects to coordinator. |
| `--token` | (none) | Telegram bot token |
| `--token-env` | (none) | Environment variable name containing the bot token |
| `--allowed-users` | (required) | Comma-separated Telegram user IDs allowed to send commands |
| `--notify-chats` | (none) | Comma-separated Telegram chat IDs for outbound notifications (`pr_created`, `pr_updated`, `run_failed`) |
| `--debug` | off | Enable debug-level logging |

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

List all signals defined in the propagate config. When multiple projects are loaded, shows signals for the active project.

### `/project [name]`

List or switch between loaded projects.

- `/project` — list all projects, marks the active one
- `/project myproject` — switch the active project for this chat

When only one project is loaded, project selection is automatic and the `/project` command is not needed.

### `/list`

List all loaded projects from the coordinator with live status, signal definitions, and active marker. Also refreshes the bot's cached project data.

Available in coordinator mode only.

### `/unload <name>`

Stop and unload a project from the coordinator.

```
/unload my-project
```

Available in coordinator mode only.

### `/reload <name>`

Reload a project — stops the worker and starts it again with a fresh config. Useful after config file changes.

```
/reload my-project
```

The bot's signal cache is automatically refreshed after reload. Available in coordinator mode only.

### `/help`

Show available commands and configured signals.

---

## Multi-Project Support

A single Telegram bot can bridge multiple propagate projects.

In coordinator mode, projects are discovered automatically from the running `propagate serve` instance. In legacy mode, pass multiple `--config` flags:

```bash
propagate-telegram \
  --config config/project-a.yaml \
  --config config/project-b.yaml \
  --token-env TELEGRAM_BOT_TOKEN \
  --allowed-users 123456
```

Each config becomes a "project" named after the config file stem (e.g. `project-a`, `project-b`). Use `/project <name>` to switch the active project before sending signals.

When only one project is loaded, all commands work without `/project` — auto-selection is applied.

Event replies are prefixed with `[project-name]` when multiple projects are loaded, so you can tell which project an event came from. With a single project, no prefix is added.

Config filenames must be unique — two configs with the same stem will be rejected.

---

## Notifications

The Telegram bot forwards certain event types to fixed chats configured via `--notify-chats` or `.env`:

- **`pr_created`** — when propagate opens a new pull request
- **`pr_updated`** — when propagate pushes more changes to a branch that already has an open PR
- **`run_failed`** — when a run fails with an error

```dotenv
TELEGRAM_BOT_TOKEN=123456:ABCDEF
TELEGRAM_USERS=123456
TELEGRAM_NOTIFY_CHATS=-1001234567890
```

```bash
propagate-telegram --token-env TELEGRAM_BOT_TOKEN --allowed-users 123456
```

Notes:

- `TELEGRAM_NOTIFY_CHATS` is a comma-separated list of Telegram chat IDs.
- These notifications are for propagate's internal events, not generic GitHub webhooks.
- If a run was started from Telegram and the origin chat is also in `TELEGRAM_NOTIFY_CHATS`, the bot sends only one message to that chat.

---

## Clarification Replies for `ask_human`

When using the MCP integration documented in [MCP.md](./MCP.md), Telegram is also the currently implemented human reply
path for the `ask_human(...)` tool.

Flow:

1. An agent calls `ask_human(question, timeout_ms=...)` through `propagate-mcp`
2. `propagate-mcp` publishes a `clarification_requested` event
3. The Telegram bot sends that clarification request to the originating chat
4. A human replies to that Telegram message
5. The bot extracts the embedded request ID and publishes `clarification_response`
6. `ask_human(...)` returns that reply text to the agent

This requires all three components to be running:

- `propagate serve`
- `propagate-telegram`
- `propagate-mcp`

There is currently no equivalent shell command for answering clarification requests.

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

# Terminal 2: start telegram bot (coordinator mode)
propagate-telegram --token-env TELEGRAM_BOT_TOKEN --allowed-users 123456
```

Send `/signal deploy Deploy to production.` in Telegram. The signal is delivered, the `deploy-app` execution starts, and the agent sees your instructions in its prompt.

---

## Auto-Reply on Events

When a signal is sent from Telegram, the bot automatically replies to the chat on key events. No extra configuration is needed — the bot subscribes to the coordinator's PUB socket (or individual worker PUB sockets in legacy mode).

The serve process remains Telegram-agnostic. It publishes generic events with an opaque `metadata` dict that the bot uses to route replies back to the originating chat.

**Architecture (coordinator mode):**

```
Telegram Bot                        Coordinator                     Worker
┌──────────────┐   ZMQ PUSH/PULL   ┌──────────────┐  PUSH/PULL   ┌──────────────┐
│ /signal go   │ ────────────────► │  route to     │ ──────────► │ receive signal│
│              │                   │  worker       │             │ run DAG       │
│              │   ZMQ PUB/SUB     │  re-publish   │  PUB/SUB    │ publish event │
│ reply to chat│ ◄──────────────── │  events       │ ◄────────── │               │
└──────────────┘                   └──────────────┘             └──────────────┘
```

### Event types

| Event | When | Message |
|-------|------|---------|
| `run_completed` | DAG finishes successfully | Run completed for signal 'X'. (+ last 3 log lines) |
| `run_failed` | DAG fails with an error | Run failed for signal 'X'. (+ last 3 log lines) |
| `waiting_for_signal` | System pauses to wait for a signal | Waiting for signal 'X' (execution 'Y'). |
| `pr_created` | A PR is opened by a git:pr hook | PR created for 'Y':\nhttps://... |
| `command_failed` | A command (e.g. /resume) fails | Command /resume failed: ... |

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
