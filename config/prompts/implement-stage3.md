# Stage 3 Implementation Task

You are implementing stage 3 of Propagate in place. The repository currently contains a working stage 2 runtime with a local context bag and prompt injection.

## Required outputs

Leave the repository in a stage 3 state. That includes:

1. Update `propagate.py` to add:
   - sub-task hooks: `before`, `after`, `on_failure`
   - config-driven context sources
   - hook-driven loading of context sources into `.propagate-context` using reserved `:`-prefixed keys
2. Preserve stage 2 behavior for:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - prompt-path resolution relative to the config file
   - prompt augmentation from the local context bag
3. Keep the implementation in a single file and keep dependencies minimal.
4. Update `config/propagate.yaml` so stage 3 targets building stage 4.
5. Create `config/prompts/design-stage4.md`, `config/prompts/implement-stage4.md`, and `config/prompts/review-stage4.md`.
   - Stage 4 is git automation.

## Stage 3 requirements

Implement hooks and context sources with straightforward stage-scoped behavior:

1. Allow each sub-task to declare optional hook command lists:
   - `before`
   - `after`
   - `on_failure`
2. Allow top-level `context_sources` definitions that describe named commands whose output becomes local context bag entries.
3. Reserve `:`-prefixed context keys for context-source values.
4. Load configured context sources via hooks before the agent command runs.
5. Keep hook execution and context-source loading deterministic and well logged.
6. Fail clearly on invalid config, hook failure, or context-source failure.
7. Do not add git behavior yet.

## Constraints

- Python 3.10+
- Use logging, not `print()`
- Use type hints
- Use f-strings
- Do not swallow exceptions
- Keep `PyYAML` as the only external dependency
- Keep prompt-file substitution via `{prompt_file}`
- Keep prompt augmentation based on `.propagate-context`

## Full Propagate vision

- Stage 1: config parsing, execution sequencing, agent execution
- Stage 2: local context bag and prompt injection
- Stage 3: hooks and context sources
- Stage 4: git automation
- Stage 5: signals and propagation triggers
- Stage 6: multi-repo and DAG orchestration

The eventual config grows into a repository-aware orchestrator with includes, defaults, repositories, propagation rules, and multiple context scopes. This task is only stage 3.

## Implementation notes

- Reuse the stage 2 context bag instead of building a second store.
- Context-source output should land in `.propagate-context/:source-name`.
- Keep the code direct and readable.
- Verify the updated CLI manually after editing.
- If `docs/hooks-and-context-sources-stage-3-design.md` exists, use it.
