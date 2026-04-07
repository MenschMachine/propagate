# Agent Interrupt & Interactive Resume

Propagate supports interrupting a running agent mid-task, dropping into an interactive session, and then resuming the
pipeline. This works in both `run` mode (Ctrl+C) and `serve` mode (via `/interrupt` in the shell).

## Run mode (Ctrl+C)

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

## Serve mode (/interrupt)

In serve mode, the worker process has no TTY. Instead, use the shell to interrupt and interact:

1. Open `propagate shell` in a separate terminal
2. Set the active project: `/project myproject`
3. Run `/interrupt`
4. The shell sends an interrupt request tagged with a per-request `interrupt_token`
5. The coordinator sends SIGUSR1 to the worker and tracks that token for the target project
6. The worker publishes exactly one final correlated outcome for the request:
   - `agent_interrupted` **only when full context is available** (`execution`, `task_id`, `working_dir`)
   - `interrupt_failed` when no agent process is running or interrupt context cannot be produced
   - both as protocol envelope messages (`protocol_version=2`, `channel=event`, `type=<event_name>`)
7. The coordinator annotates with `project` + `interrupt_token`, and the shell waits only for that exact pair
8. The shell treats `/interrupt` as complete only on one of those final outcomes (default wait `15s`, configurable via
   `PROPAGATE_INTERRUPT_CONTEXT_TIMEOUT`)
9. This guarantee also applies during worker startup auto-resume (`propagate serve --resume` or existing state on boot):
   startup `AgentInterrupted` is finalized through the same interrupt outcome path, so shell does not time out waiting
   for a missing final event
10. On success, the shell prints interrupted execution/task/working directory and then asks rerun/skip/abort
11. You open another terminal to interact with the agent manually
12. When you're done, return to the shell and choose rerun/skip/abort
13. The shell sends the chosen action back to the worker and waits for a final correlated outcome
14. The worker publishes exactly one resume terminal outcome for the same `project + interrupt_token`:
    - `interrupt_resumed` for `rerun` / `skip` immediately after the action is accepted and context is validated (before long resume execution)
    - `interrupt_aborted` for `abort` after worker confirms stop/no-resume
    - `interrupt_resume_failed` when action is invalid, metadata is incomplete, or resume fails
15. The shell prints success only after terminal acknowledgment (default wait `15s`, configurable via
    `PROPAGATE_INTERRUPT_RESUME_TIMEOUT`)

```
propagate> /interrupt
Interrupt sent to 'myproject'. Waiting for agent to stop...

--- Interrupted execution 'analyze', task 'generate-plan'. ---
  Working directory: /path/to/repo
  Agent command:     claude -p {prompt_file}

You can now open another terminal to interact with the agent.
When you're done, choose how to continue:

[R]erun task / [S]kip to next / [A]bort? r
Resume (rerun) acknowledged by 'myproject'.
```

## Interactive command

The interactive session command is derived from the configured agent command by removing the `{prompt_file}` placeholder.
For example:

| Agent command | Interactive command |
|---|---|
| `claude -p {prompt_file}` | `claude -p` |
| `claude --prompt-file {prompt_file}` | `claude --prompt-file` |
| `my-agent {prompt_file} --verbose` | `my-agent --verbose` |

The interactive agent inherits the full terminal (TTY), so you get a normal interactive session.

## Notes

- Interrupts during hook phases (before/after/on_failure) are not intercepted — in run mode they trigger the standard
  `KeyboardInterrupt` exit with resume hint; in serve mode they are logged as errors
- On_failure hooks do **not** run when an agent is interrupted — this is a user-initiated action, not a failure
- `/interrupt` outcomes are correlated by both `project` and `interrupt_token` to avoid cross-project or stale-event races
- `interrupt_resume` outcomes are also correlated by both `project` and `interrupt_token`; shell does not print optimistic
  success before worker acknowledgment
- Shell never renders placeholder interrupt context (`unknown` / `pending`); missing context is treated as `interrupt_failed`
- Shell rendering remains dialog-only: acknowledgements are shown, but background log events are buffered for `/logs` only

## Compatibility with --resume

If you choose **Abort**, the state file has the interrupted task's agent phase incomplete. Running
`propagate run --config ... --resume` will pick up from that task.
