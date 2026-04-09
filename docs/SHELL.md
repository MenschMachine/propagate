# Interactive Shell

The `propagate shell` command provides a local terminal REPL for interacting with a running `propagate serve` instance.
It connects to the coordinator's ZMQ sockets to send signals, commands, and manage projects.

## Usage

Start a serve instance in one terminal:

```bash
propagate serve --config config/propagate.yaml
```

Connect with the shell in another terminal:

```bash
propagate shell
```

### Legacy mode

To connect directly to a single config's sockets (bypassing the coordinator):

```bash
propagate shell --config config/propagate.yaml
```

## Commands

### Coordinator mode (default, no `--config`)

| Command | Description |
|---------|-------------|
| `/list` | List all loaded projects with status and signals |
| `/load <path>` | Load a config as a new project |
| `/unload <name>` | Stop and unload a project |
| `/reload <name>` | Reload a project (stop + start) |
| `/project [name]` | Show or set the active project |
| `/signal <type> [key:val ...]` | Send a signal (requires active project) |
| `/resume` | Resume a failed run (requires active project) |
| `/interrupt` | Interrupt running agent, start interactive session |
| `/signals` | List signals for the active project |
| `/logs [N]` | Show last N log lines (default 20) |
| `/help` | Show available commands |
| `/quit`, `/exit` | Exit the shell (also Ctrl-D) |

### Legacy mode (`--config`)

| Command | Description |
|---------|-------------|
| `/signal <type> [key:val ...]` | Send a signal to the running instance |
| `/resume` | Resume a failed or interrupted run |
| `/signals` | List configured signals with their fields |
| `/logs [N]` | Show last N log lines from the server (default 20) |
| `/help` | Show available commands |
| `/quit`, `/exit` | Exit the shell (also Ctrl-D) |

## Project Management

In coordinator mode, use `/list` to see available projects and `/project <name>` to select one before sending signals:

```
propagate> /list
  my-project [running] — signals: deploy, build
  other-project [running] — signals: test
propagate> /project my-project
Switched to project 'my-project'.
propagate> /signal deploy branch:main
Signal 'deploy' delivered to 'my-project'.
```

With a single project loaded, it is auto-selected. No `/project` command needed.

## Dynamic Loading

Load and unload projects at runtime:

```
propagate> /load /path/to/config.yaml
Loaded project 'config'.
propagate> /unload config
Unloaded project 'config'.
propagate> /reload config
Reloaded project 'config'.
```

## Sending Signals

Signals are sent as `/signal <type>` followed by `key:value` pairs:

```
propagate> /signal deploy url:https://github.com/org/repo env:production
Signal 'deploy' delivered to 'my-project'.
```

When a signal has exactly one user-facing field, you can omit the key:

```
propagate> /signal feedback This is my feedback message
Signal 'feedback' delivered to 'my-project'.
```

Quoted values are supported for values containing spaces:

```
propagate> /signal deploy "message:hello world"
```

## Event Visibility Policy

The shell does **not** print background worker/coordinator events while you type commands.

- Logs are buffered locally and shown only when you run `/logs [N]`.
- Lifecycle events and notifications are not auto-printed to avoid prompt corruption and random output pop-ins.
- Command output and interactive dialog prompts remain the only shell-rendered output.

## Protocol Envelope

Shell/coordinator/worker communication on PUB/SUB uses a versioned envelope.

- `protocol_version`: protocol version number (`2` for current format)
- `channel`: message channel (`event`)
- `type`: normalized event type (for example `command_reply`, `agent_interrupted`, `interrupt_failed`, `log`)
- `event`: legacy mirror of `type` for compatibility inside the codebase

The shell routes by `type` first and never renders `log` events except through `/logs`.

## Interrupt Acknowledgment Matching

When you run `/interrupt`, the shell creates a per-request `interrupt_token` and sends it with the active `project`.

- The shell waits for a final interrupt outcome (`agent_interrupted` or `interrupt_failed`) that matches **both** `project` and `interrupt_token`.
- `agent_interrupted` is accepted only when required context is present (`execution`, `task_id`, `working_dir`).
- If context is missing or timeout is reached, `/interrupt` fails explicitly and does not open the resume prompt.
- Interrupts that occur while a worker is auto-resuming on startup are finalized through the same path, so `/interrupt` receives a normal final outcome instead of timing out.
- Unrelated interrupt events (different project or stale token) are ignored for that request.
- Default wait is `15s`, configurable via `PROPAGATE_INTERRUPT_CONTEXT_TIMEOUT`.

## Interrupt Resume Acknowledgment Matching

After you choose `[R]erun`, `[S]kip`, or `[A]bort`, the shell sends `interrupt_resume` with the same `project` and
`interrupt_token` and then waits for one terminal correlated worker outcome:

- `interrupt_resumed` (for `rerun` / `skip`) — resume action was accepted and correlated before long resume execution continues
- `interrupt_aborted` (for `abort`) — abort action was applied
- `interrupt_resume_failed` — action rejected/failed (invalid action, missing metadata, resume failure, etc.)

The shell prints success only after receiving one of the matching terminal events above (not immediately after sending).
Default resume-ack wait is `15s`, configurable via `PROPAGATE_INTERRUPT_RESUME_TIMEOUT`.

Coordinator-side strictness for this flow:

- `interrupt_resume` is forwarded to worker only when there is an active interrupt session for the same `project` in `waiting_resume_action`.
- Missing/stale/mismatched tokens are rejected as terminal `interrupt_resume_failed` events (not forwarded), so shell gets deterministic failure outcomes instead of hanging.

## Notes

- The log buffer starts empty on each connect. ZMQ PUB/SUB does not replay messages sent before the subscription, so
  `/logs` only shows lines received since the shell was started.
- The `sender` payload field (if defined on a signal) is automatically set to the OS username.

## How It Works

### Coordinator mode (default)

The shell connects two ZMQ sockets to the coordinator:

- **PUSH socket** → `ipc:///tmp/propagate-coordinator.sock` — sends signals, commands, and coordinator actions
- **SUB socket** ← `ipc:///tmp/propagate-coordinator-pub.sock` — receives events from all workers

### Legacy mode (`--config`)

The shell connects directly to a single config's sockets:

- **PUSH socket** — sends signals and commands (hash-based address)
- **SUB socket** — receives published events (hash-based address)

A background daemon thread polls the SUB socket and only enqueues protocol events / buffers logs.
The main thread is the single renderer and runs the input loop with readline support for line editing and history.
