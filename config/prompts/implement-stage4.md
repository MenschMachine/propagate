# Stage 4 Implementation Task

You are implementing stage 4 of Propagate in place. The repository currently contains a working stage 3 runtime with hooks, context sources, a local context bag, and prompt injection.

## Required outputs

Leave the repository in a stage 4 state. That includes:

1. Update `propagate.py` to add git automation for successful runs.
2. Preserve stage 3 behavior for:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - hook execution
   - context-source loading
   - prompt-path resolution relative to the config file
   - prompt augmentation from `.propagate-context`
3. Keep the implementation in a single file and keep dependencies minimal.
4. Update `config/propagate.yaml` so stage 4 targets stage 5.
5. Create the next design, implementation, and review prompts for stage 5.

## Stage 4 requirements

Implement only stage-scoped git automation:

1. Support config-driven branch creation and checkout.
2. Commit successful changes after the execution completes.
3. Support pushing when configured.
4. Support PR creation when configured.
5. Source commit messages from a configured context source or reserved context key.
6. Keep git execution deterministic and well logged.
7. Fail clearly on invalid config or git command failure.

## Constraints

- Python 3.10+
- Use logging, not `print()`
- Use type hints
- Use f-strings
- Do not swallow exceptions
- Keep `PyYAML` as the only external dependency
- Keep prompt-file substitution via `{prompt_file}`
- Treat hooks and context sources as already available
- Do not add signals, propagation triggers, or multi-repo behavior yet

## Full Propagate vision

- Stage 1: config parsing, execution sequencing, agent execution
- Stage 2: local context bag and prompt injection
- Stage 3: hooks and context sources
- Stage 4: git automation
- Stage 5: signals and propagation triggers
- Stage 6: multi-repo and DAG orchestration

## Implementation notes

- Keep git behavior repository-local.
- Reuse the existing context bag for commit-message inputs.
- Do not expand into repository registries or orchestration.
- Verify the updated CLI manually after editing.
