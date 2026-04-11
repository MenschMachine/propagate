# Serve Mode

`propagate serve` runs Propagate as a long-lived server using a coordinator/worker architecture. The coordinator process manages worker subprocesses, each handling one config. Clients (shell, telegram) connect to the coordinator via well-known sockets.

---

## Usage

```bash
# Start with pre-loaded configs
propagate serve --config config/propagate.yaml

# Multiple configs
propagate serve --config config/project-a.yaml --config config/project-b.yaml

# Start empty, load configs dynamically via shell
propagate serve
```

The `--config` flag is optional and repeatable. Configs can also be loaded/unloaded at runtime via the shell or telegram bot.

---

## Architecture

```
propagate serve [--config a.yaml --config b.yaml]
  └─ Coordinator (main process)
     ├─ Binds PULL socket: ipc:///tmp/propagate-coordinator.sock
     ├─ Binds PUB socket:  ipc:///tmp/propagate-coordinator-pub.sock
     ├─ Spawns worker subprocesses via: propagate serve-worker --config x.yaml
     ├─ Connects PUSH to each worker's PULL (hash-based address)
     ├─ Subscribes SUB to each worker's PUB (hash-based address)
     ├─ Re-publishes worker events on coordinator PUB with "project" field
     ├─ Routes signals/commands to correct worker based on "project" in metadata
     └─ Monitors worker health (detects unexpected death)

Clients (shell, telegram):
  └─ Connect PUSH to coordinator PULL + SUB to coordinator PUB
     └─ Never talk directly to workers
```

Workers are separate OS processes, eliminating GIL contention. Each worker binds its own PULL + PUB sockets (hash-based addresses, same as before).

---

## How it works

1. Coordinator binds well-known PULL + PUB sockets
2. For each `--config`, spawn a worker subprocess (`propagate serve-worker --config x.yaml`)
3. Worker binds its own PULL + PUB sockets, prints `READY` to stdout
4. Coordinator connects PUSH + SUB to each worker's sockets
5. Enter main loop: receive messages on coordinator PULL, route to workers or handle coordinator commands
6. Worker events are re-published on coordinator PUB with a `"project"` field added
7. On SIGTERM or SIGINT, SIGTERM all workers, wait, then exit

---

## Coordinator commands

The coordinator accepts these commands on its PULL socket (in addition to forwarding signals/commands to workers):

| Command | Description |
|---------|-------------|
| `list` | List all loaded projects with status and signal definitions |
| `load` | Load a new config as a worker subprocess |
| `unload` | Stop and remove a project |
| `reload` | Stop and restart a project (unload + load) |
| `event` | Publish an integration event (for example `clarification_requested` / `clarification_response`) to coordinator PUB subscribers |

Responses are published on the coordinator PUB socket as `coordinator_response` events.

---

## Dynamic project management

Projects can be loaded and unloaded at runtime without restarting the server:

```
# Via shell
propagate shell
propagate> /load config/new-project.yaml
propagate> /list
propagate> /unload new-project
propagate> /reload existing-project
```

---

## Sending signals to the server

### Via coordinator (recommended)

Signals include a `"project"` field in metadata to route to the correct worker:

```bash
propagate send-signal --project my-project \
  --signal deploy \
  --signal-payload '{branch: main}'
```

### Via config path (backward compatible)

```bash
propagate send-signal --config config/propagate.yaml \
  --signal deploy \
  --signal-payload '{branch: main}'
```

This connects directly to the worker's socket (bypassing the coordinator).

---

## Auto-resume on startup

If a state file (`.propagate-state-{name}.yaml`) exists when a worker starts, it resumes from that saved run state before entering the serve loop. This handles crash recovery — if the server was killed mid-run, restarting it picks up where it left off. State files are retained until `propagate clear`, so a fully completed run may also be loaded and immediately no-op.

Entry-signal queue state is persisted separately in `.propagate-queue-{name}.yaml`. Any queued entry signals left from a previous process are drained in FIFO order after startup resume completes (or immediately on startup if no resume is needed).

---

## Error handling

- **Unknown signal type**: logged as a warning, ignored. The worker continues.
- **Invalid payload** (missing required fields, wrong types): logged as a warning, ignored.
- **Execution failure** (`PropagateError` during a run): logged as an error. The worker continues listening.
- **Worker death**: coordinator detects via health check, publishes `worker_died` event. No auto-restart.
- **Unknown project**: coordinator responds with an error message.

---

## Graceful shutdown

The coordinator handles SIGTERM and SIGINT:

1. Shutdown flag is set
2. SIGTERM sent to all worker processes
3. Wait up to 5 seconds per worker, then SIGKILL if needed
4. Coordinator sockets closed and cleaned up

Workers handle SIGTERM independently — they finish the current operation and exit.

---

## Event Publishing (PUB/SUB)

Each worker binds a ZMQ PUB socket at `ipc:///tmp/propagate-pub-{hash}.sock`. The coordinator subscribes to all workers and re-publishes events on `ipc:///tmp/propagate-coordinator-pub.sock` with a `"project"` field added.

Clients should subscribe to the coordinator PUB socket to receive events from all projects.

### Event types

| Event | Source | Fields |
|-------|--------|--------|
| `run_completed` | After a DAG finishes | `signal_type`, `metadata`, `messages`, `project` |
| `run_failed` | After a DAG fails | `signal_type`, `metadata`, `messages`, `project` |
| `entry_signal_queued` | Entry signal added while backlog exists (`pending_count > 1`) | `signal_type`, `initial_execution`, `sequence`, `pending_count`, `metadata`, `project` |
| `entry_signal_dequeued` | Queued signal selected while backlog remains (`pending_count > 0`) | `signal_type`, `initial_execution`, `sequence`, `pending_count`, `metadata`, `project` |
| `waiting_for_signal` | Scheduler pauses for a signal | `execution`, `signal`, `metadata`, `project` |
| `pr_created` | Git PR hook creates a PR | `execution`, `pr_url`, `metadata`, `project` |
| `command_failed` | Command (e.g. resume) fails | `command`, `message`, `metadata`, `project` |
| `log` | Each log message | `line`, `project` |
| `coordinator_response` | Coordinator command result | `request_id`, `data` or `error` |
| `worker_died` | Worker process died | `project` |

---

## Limitations

- **Sequential execution per worker.** Each worker handles one DAG at a time. Entry signals are persisted and processed one-by-one.
- **Strict FIFO for entry signals.** Entry signals run in global arrival order for each worker.
- **No deduplication.** The same signal sent twice triggers two separate runs.
- **Each signal type must map to exactly one execution.** Use `when` filters to disambiguate.
- **No auto-restart.** If a worker dies, it must be reloaded manually via `/load` or `/reload`.
- **Webhook is single-config only.** Webhooks don't support coordinator routing.

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

# Terminal 2: interact via shell
propagate shell
propagate> /list
propagate> /signal deploy branch:main
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
