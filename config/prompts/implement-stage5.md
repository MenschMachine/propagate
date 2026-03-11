# Stage 5 Implementation Task

You are implementing stage 5 of Propagate in place. The repository currently contains a working stage 4 runtime with hooks, context sources, a local context bag, prompt injection, and repository-local git automation.

## Required outputs

Leave the repository in a stage 5 state. That includes:

1. Update `propagate.py` to add signals and propagation triggers.
2. Preserve stage 4 behavior for:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - hook execution
   - context-source loading
   - prompt-path resolution relative to the config file
   - prompt augmentation from `.propagate-context`
   - stage-scoped git automation
3. Keep the implementation in a single file and keep dependencies minimal.
4. Update `config/propagate.yaml` so stage 5 targets stage 6.
5. Create the next design, implementation, and review prompts for stage 6.

## Stage 5 requirements

Implement only stage-scoped signal and trigger behavior:

1. Support config-defined signal schemas or signal types.
2. Support providing a signal to `propagate run`.
3. Populate the local context bag from the active signal payload.
4. Support config-defined propagation triggers between executions in the current repository.
5. Select or enqueue follow-on executions deterministically after a successful source execution.
6. Keep signal handling and trigger evaluation well logged.
7. Fail clearly on invalid config, malformed signal input, or invalid trigger references.

## Constraints

- Python 3.10+
- Use logging, not `print()`
- Use type hints
- Use f-strings
- Do not swallow exceptions
- Keep `PyYAML` as the only external dependency
- Keep prompt-file substitution via `{prompt_file}`
- Treat hooks, context sources, and git automation as already available
- Do not add multi-repo orchestration or full DAG scheduling yet

## Full Propagate vision

- Stage 1: config parsing, execution sequencing, agent execution
- Stage 2: local context bag and prompt injection
- Stage 3: hooks and context sources
- Stage 4: git automation
- Stage 5: signals and propagation triggers
- Stage 6: multi-repo and DAG orchestration

## Implementation notes

- Keep signal and trigger behavior repository-local.
- Reuse the existing context bag for signal payload values.
- Do not expand into repository registries or cross-repo execution.
- Verify the updated CLI manually after editing.
