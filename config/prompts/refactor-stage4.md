# Stage 4 Refactor Task

You are refactoring the stage 4 implementation of Propagate. The runtime should already include stage-3 hooks and context sources plus stage-4 git automation.

## Refactor goals

1. Improve clarity and maintainability of the stage 4 implementation in `propagate.py`.
2. Preserve behavior for:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - deterministic context injection from `.propagate-context`
   - `before`, `after`, and `on_failure` hooks
   - named `context_sources`
   - validation-oriented hooks around agent execution
   - branch creation, checkout, and reuse
   - commit creation after successful runs
   - push and PR creation when configured
   - commit-message sourcing from context
3. Do not expand scope beyond stage 4.

## Constraints

- Keep the implementation in `propagate.py`
- Keep `PyYAML` as the only external dependency
- Keep prompt-path resolution relative to the config file
- Keep agent execution in the invocation working directory
- Reuse the existing local context bag instead of introducing another store

## Bootstrap check

Keep the repository targeting stage 5:

- `config/propagate.yaml` should target `build-stage5`
- all six stage-5 prompt files should exist and stay focused on signals and propagation triggers
