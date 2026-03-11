# Stage 5 Refactor Task

You are refactoring the stage 5 implementation of Propagate. The runtime should already include stage-4 git automation plus stage-5 signals and propagation triggers.

## Refactor goals

1. Improve clarity and maintainability of the stage 5 implementation in `propagate.py`.
2. Preserve behavior for:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - deterministic context injection from `.propagate-context`
   - `before`, `after`, and `on_failure` hooks
   - named `context_sources`
   - validation-oriented hooks around agent execution
   - git branch, commit, push, and PR behavior
   - signal ingestion and context population from payloads
   - trigger matching and follow-on execution selection
3. Do not expand scope beyond stage 5.

## Constraints

- Keep the implementation in `propagate.py`
- Keep `PyYAML` as the only external dependency
- Keep prompt-path resolution relative to the config file
- Keep agent execution in the invocation working directory
- Reuse the existing local context bag instead of introducing another store

## Bootstrap check

Keep the repository targeting stage 6:

- `config/propagate.yaml` should target `build-stage6`
- all six stage-6 prompt files should exist and stay focused on multi-repo and DAG orchestration
