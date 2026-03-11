# Stage 3 Refactor Task

You are refactoring the stage 3 implementation of Propagate. The runtime should already include stage-2 local context bag behavior plus stage-3 hooks and named context sources.

## Refactor goals

1. Improve clarity and maintainability of the stage 3 implementation in `propagate.py`.
2. Preserve behavior for:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - deterministic context injection from `.propagate-context`
   - `before`, `after`, and `on_failure` hooks
   - named `context_sources`
   - validation-oriented hooks around agent execution
3. Do not expand scope beyond stage 3.

## Constraints

- Keep the implementation in `propagate.py`
- Keep `PyYAML` as the only external dependency
- Keep prompt-path resolution relative to the config file
- Keep agent execution in the invocation working directory
- Reuse the existing local context bag instead of introducing another store

## Bootstrap check

Keep the repository targeting stage 4:

- `config/propagate.yaml` should target `build-stage4`
- stage-4 prompt files should exist and stay focused on git automation
