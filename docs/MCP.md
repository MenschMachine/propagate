# MCP Integration

`propagate-mcp` exposes Propagate-specific MCP tools to an MCP-capable agent client. Today the main tool is
`ask_human(question, timeout_ms=...)`, which lets an agent pause for clarification from a human and continue once a
reply arrives. Some agent clients may present the same capability to the model as `ask_user`; in this repository and
server code, the tool is named `ask_human`.

This is separate from the Propagate YAML engine:

- `propagate serve` runs workflows
- `propagate-telegram` delivers clarification requests to a human and sends replies back
- `propagate-mcp` is the MCP server process that exposes the tool to the agent client

If you are only using normal Propagate signals, hooks, `wait_for_signal`, shell, webhook, or Telegram-triggered runs,
you do not need `propagate-mcp`.

---

## Installation

Install the MCP extra so the `mcp` dependency and `propagate-mcp` console script are available:

```bash
./venv/bin/pip install -e .[mcp]
```

If you also want the human reply path via Telegram:

```bash
./venv/bin/pip install -e .[mcp,telegram]
```

---

## What `ask_human` does

When an agent calls `ask_human(...)`:

1. `propagate-mcp` publishes a `clarification_requested` event to the coordinator socket
2. The event includes a generated `request_id`
3. `propagate-mcp` waits for a matching `clarification_response`
4. The response text is returned to the agent as the tool result

The implementation lives in [propagate_mcp/server.py](../propagate_mcp/server.py).

---

## Required Processes

To use `ask_human` end-to-end:

1. `propagate serve`
2. `propagate-telegram`
3. an active `propagate-mcp` server process

Why:

- `propagate serve` provides the coordinator sockets used by the MCP server
- `propagate-telegram` is the currently implemented human reply path
- `propagate-mcp` is the MCP server process the agent client connects to

There is currently no built-in shell command for answering `clarification_requested` messages. The implemented reply
path is Telegram replies to the bot's clarification message.

In a typical MCP setup, you do not start `propagate-mcp` manually. Your MCP client starts it as a subprocess using the
configured command. The important requirement is that a `propagate-mcp` server process is running when the agent calls
`ask_human(...)`.

---

## Starting the Services

Example:

```bash
# Terminal 1
./venv/bin/propagate serve --config config/propagate.yaml

# Terminal 2
./venv/bin/propagate-telegram --token-env TELEGRAM_BOT_TOKEN --allowed-users 123456
```

In a normal MCP client setup, you do not start `propagate-mcp` in a separate terminal. The client launches it when it
connects to the MCP server entry you configured.

---

## Configuring the Agent Client

You do not configure `ask_human` in `propagate.yaml`. You configure your MCP-capable agent client to spawn the
`propagate-mcp` server.

Typical MCP client configuration:

```json
{
  "mcpServers": {
    "propagate": {
      "command": "propagate-mcp"
    }
  }
}
```

If you prefer an explicit Python entrypoint:

```json
{
  "mcpServers": {
    "propagate": {
      "command": "/Users/michael/Code/TFC/propagate/venv/bin/python",
      "args": ["-m", "propagate_mcp.cli"]
    }
  }
}
```

The exact file location for MCP config depends on the client you use. The important part is that the client spawns
`propagate-mcp` as an MCP server subprocess.

After adding the server entry, restart the client so it discovers the `ask_human` tool.

---

## Agent Usage

From the agent's perspective, usage is just a normal MCP tool call:

```python
answer = ask_human("Should I merge this as-is, or revise the docs first?")
```

The call blocks until one of these happens:

- a matching clarification reply arrives
- the timeout expires

The default timeout is 1 hour.

---

## Human Reply Flow

When `ask_human` publishes a clarification request:

1. The Telegram bot receives the `clarification_requested` event
2. It sends a message containing the question and request ID (to the originating chat when available, and to configured notify chats)
3. The human replies to that Telegram message
4. The bot extracts the request ID from the replied-to message
5. The bot publishes `clarification_response`
6. `ask_human` returns the answer string to the agent

The Telegram reply handler lives in [propagate_telegram/bot.py](../propagate_telegram/bot.py).

---

## Optional Metadata

`ask_human` reads a few environment variables if present:

- `PROPAGATE_PROJECT`
- `PROPAGATE_EXECUTION`
- `PROPAGATE_METADATA`

These are used to annotate the clarification event with project and execution context. They are useful for routing and
display, but the tool can still run without them.

---

## Relationship to `wait_for_signal`

`ask_human` is not the same as YAML `wait_for_signal`.

- `ask_human` is an MCP tool call made by the agent at runtime
- `wait_for_signal` is a declarative workflow gate in `propagate.yaml`

Use `wait_for_signal` when the workflow should pause on a named external signal. Use `ask_human` when the agent itself
needs ad hoc clarification mid-task.
