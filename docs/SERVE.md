# Serve Mode

`propagate serve` runs Propagate as a long-lived server that listens for signals on a ZeroMQ socket and executes the corresponding DAG for each one.

---

## Usage

```bash
propagate serve --config config/propagate.yaml
```

The `--config` flag is repeatable. Pass multiple configs to serve them all from a single process:

```bash
propagate serve --config config/project-a.yaml --config config/project-b.yaml
```

The server binds a ZMQ PULL socket unconditionally (not gated on whether signal-gated triggers exist) and waits for incoming signals.

---

## How it works

1. Load config from the specified YAML file(s)
2. Bind ZMQ PULL socket at `ipc:///tmp/propagate-{hash}.sock` per config
3. If a state file exists from a previous interrupted run, resume it
4. Enter the serve loop: poll for signals, run the matching execution DAG for each one
5. On SIGTERM or SIGINT, finish the current operation and exit

Signals are processed sequentially — one DAG runs to completion before the next signal is handled.

---

## Multi-config mode

When multiple `--config` flags are passed, each config runs in its own thread with isolated ZMQ sockets. They share a single shutdown event — a SIGTERM or SIGINT stops all configs.

Each thread's ZMQ log handler is filtered to only publish log messages originating from its own thread, preventing cross-talk between configs.

Configs are completely independent: each has its own PULL socket, PUB socket, serve loop, and state file. Signals sent to one config's socket are not visible to the others.

Config filenames must be unique — two configs with the same stem (e.g. `repos/a/propagate.yaml` and `repos/b/propagate.yaml`) will be rejected at startup.

If one config fails (e.g. socket bind error), all configs are shut down and the error is logged.

**Note:** When using `scripts/start.sh` with multiple configs, the webhook service only receives the first config. Webhooks are per-repository and don't support multi-config routing.

---

## Sending signals to the server

Use `propagate send-signal` from another terminal:

```bash
propagate send-signal --config config/propagate.yaml \
  --signal deploy \
  --signal-payload '{branch: main}'
```

Or via a webhook receiver that pushes signals to the same ZMQ socket.

The `--config` path must match the one used by the running `propagate serve` instance.

---

## Auto-resume on startup

If a state file (`.propagate-state-{name}.yaml`) exists when the server starts, it resumes the interrupted run before entering the serve loop. This handles crash recovery — if the server was killed mid-run, restarting it picks up where it left off.

---

## Error handling

- **Unknown signal type**: logged as a warning, ignored. The server continues.
- **Invalid payload** (missing required fields, wrong types): logged as a warning, ignored.
- **Execution failure** (`PropagateError` during a run): logged as an error. The server continues listening for the next signal.
- The server never crashes on a bad signal or failed run.

---

## Graceful shutdown

The server handles SIGTERM and SIGINT. When received:

1. A shutdown flag is set
2. If a DAG is currently running, it runs to completion (or until the scheduler saves state on `KeyboardInterrupt`)
3. The serve loop exits cleanly
4. The ZMQ socket is closed and cleaned up

If the process is killed during an active run, the scheduler saves state via `_sync_and_save`. On next startup, auto-resume picks it up.

---

## Event Publishing (PUB/SUB)

In addition to the PULL socket for receiving signals, the server binds a ZMQ PUB socket at `ipc:///tmp/propagate-pub-{hash}.sock`. After each run completes or fails, a JSON event is published:

```json
{
  "event": "run_completed",
  "signal_type": "deploy",
  "metadata": {},
  "messages": ["last", "three", "log messages"]
}
```

### Event types

| Event | Source | Fields |
|-------|--------|--------|
| `run_completed` | After a DAG finishes | `signal_type`, `metadata`, `messages` |
| `run_failed` | After a DAG fails | `signal_type`, `metadata`, `messages` |
| `waiting_for_signal` | When the scheduler or a sub-task pauses waiting for a signal | `execution`, `signal`, `metadata` |
| `pr_created` | When a `git:pr` hook creates a PR | `execution`, `pr_url`, `metadata` |
| `command_failed` | When a command (e.g. resume) fails | `command`, `message`, `metadata` |
| `log` | On each log message (for live streaming) | `line` |

- `metadata`: opaque dict forwarded from the incoming ZMQ message (never touches signal validation)
- `messages`: last 3 log messages from the `propagate` logger during the run

Any ZMQ SUB client can subscribe to these events. The Telegram bot uses this to auto-reply to the chat that triggered the signal (see [TELEGRAM.md](TELEGRAM.md#auto-reply-on-events)).

The server knows nothing about subscribers — it publishes events regardless of whether anyone is listening.

---

## Limitations

- **Config is loaded once at startup.** Changes to the config file require restarting the server.
- **Sequential execution.** Only one DAG runs at a time. Signals received during an active run are buffered by the ZMQ socket and processed one at a time after the current run completes. However, signals that arrive during an active run and match a pending propagation trigger within that run are consumed by the scheduler's drain loop — they won't trigger a separate serve-level run.
- **No deduplication.** The same signal sent twice triggers two separate runs.
- **Each signal type must map to exactly one execution.** Serve mode has no `--execution` flag, so execution selection is automatic. If multiple executions accept the same signal type (and payload filters don't disambiguate), every instance of that signal will fail with an error and no run will start. Use `when` filters to ensure each signal resolves to a single execution.
- **Webhook is single-config only.** When using multi-config mode with `scripts/start.sh`, the webhook service only receives the first config. Webhooks are per-repository and don't support multi-config routing.

---

## Example

```yaml
# config/propagate.yaml
version: "6"

agent:
  command: claude --dangerously-skip-permissions

signals:
  deploy:
    payload:
      branch:
        type: string
        required: true

repositories:
  app:
    path: .

executions:
  deploy-app:
    repository: app
    signals: [deploy]
    sub_tasks:
      - id: deploy
        prompt: ./prompts/deploy.md
```

```bash
# Terminal 1: start the server
propagate serve --config config/propagate.yaml

# Terminal 2: trigger a deploy
propagate send-signal --config config/propagate.yaml \
  --signal deploy \
  --signal-payload '{branch: main}'
```

---

## Unified start script

To start all services (`serve`, `webhook`, `telegram`) together with merged, labeled output:

```bash
scripts/start.sh --config config/propagate.yaml

# Multiple configs:
scripts/start.sh --config config/project-a.yaml --config config/project-b.yaml

# Add --dev to also start smee for local webhook forwarding:
scripts/start.sh --config config/propagate.yaml --dev

# See all options:
scripts/start.sh --help
```
