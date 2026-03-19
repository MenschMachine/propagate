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

## Event Streaming

Events published by workers (signal received, run completed, PR created, etc.) are printed in real-time
above the input prompt. In coordinator mode, events are prefixed with `[project-name]`. Log output is
buffered locally and can be viewed with `/logs`.

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

A background daemon thread polls the SUB socket and prints formatted events. The main thread runs the input loop with
readline support for line editing and history.
