# Interactive Shell

The `propagate shell` command provides a local terminal REPL for interacting with a running `propagate serve` instance.
It connects over ZMQ to send signals and commands, and streams events back in real-time.

## Usage

Start a serve instance in one terminal:

```bash
propagate serve --config config/propagate.yaml
```

Connect with the shell in another terminal:

```bash
propagate shell --config config/propagate.yaml
```

The `--config` path must match the one used by `serve` — it determines the ZMQ socket address.

## Commands

| Command | Description |
|---------|-------------|
| `/signal <type> [key:val ...]` | Send a signal to the running instance |
| `/resume` | Resume a failed or interrupted run |
| `/signals` | List configured signals with their fields |
| `/logs [N]` | Show last N log lines from the server (default 20) |
| `/help` | Show available commands |
| `/quit`, `/exit` | Exit the shell (also Ctrl-D) |

## Sending Signals

Signals are sent as `/signal <type>` followed by `key:value` pairs:

```
propagate> /signal deploy url:https://github.com/org/repo env:production
Signal 'deploy' delivered.
```

When a signal has exactly one user-facing field, you can omit the key:

```
propagate> /signal feedback This is my feedback message
Signal 'feedback' delivered.
```

Quoted values are supported for values containing spaces:

```
propagate> /signal deploy "message:hello world"
```

## Event Streaming

Events published by the serve instance (signal received, run completed, PR created, etc.) are printed in real-time
above the input prompt. Log output from the server is buffered locally and can be viewed with `/logs`.

## Notes

- The log buffer starts empty on each connect. ZMQ PUB/SUB does not replay messages sent before the subscription, so
  `/logs` only shows lines received since the shell was started.
- The `sender` payload field (if defined on a signal) is automatically set to the OS username.

## How It Works

The shell connects two ZMQ sockets to the serve instance:

- **PUSH socket** — sends signals and commands (same address as `send-signal` CLI)
- **SUB socket** — receives published events (PUB/SUB pattern)

A background daemon thread polls the SUB socket and prints formatted events. The main thread runs the input loop with
readline support for line editing and history.
