# Agent Interrupt & Interactive Resume

Propagate supports interrupting a running agent mid-task, dropping into an interactive session, and then resuming the
pipeline.

## How it works

1. While an agent sub-task is running, press **Ctrl+C**
2. Propagate terminates the agent subprocess gracefully (SIGTERM, then SIGKILL after 10s timeout)
3. Run state is preserved — the interrupted task's agent phase is **not** marked complete
4. An interactive agent session launches in the same working directory
5. You interact with the agent directly (clarify intent, fix issues, make changes)
6. When you exit the interactive session, Propagate prompts:

```
[R]erun task / [S]kip to next / [A]bort?
```

- **Rerun** — re-executes the interrupted task from the agent phase (before hooks are skipped if already completed)
- **Skip** — marks the agent phase complete and continues to after hooks and the next task
- **Abort** — exits with code 130, prints resume hint for later `--resume`

## Interactive command

The interactive session command is derived from the configured agent command by removing the `{prompt_file}` placeholder.
For example:

| Agent command | Interactive command |
|---|---|
| `claude -p {prompt_file}` | `claude -p` |
| `claude --prompt-file {prompt_file}` | `claude --prompt-file` |
| `my-agent {prompt_file} --verbose` | `my-agent --verbose` |

The interactive agent inherits the full terminal (TTY), so you get a normal interactive session.

## Scope

- Works in `propagate run` mode only (requires a TTY)
- Does **not** apply to `propagate serve` — Ctrl+C in serve mode triggers graceful shutdown as before
- Interrupts during hook phases (before/after/on_failure) are not intercepted — they trigger the standard
  `KeyboardInterrupt` exit with resume hint

## Compatibility with --resume

If you choose **Abort**, the state file has the interrupted task's agent phase incomplete. Running
`propagate run --config ... --resume` will pick up from that task.
