# Stage 5 Test Task

You are testing the stage 5 implementation of Propagate. The runtime should extend stage 4 with signals and propagation triggers while preserving hooks, context sources, the local `.propagate-context` bag, deterministic prompt augmentation, and git automation.

## Test goals

1. Verify stage 4 behavior still works:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - `.propagate-context` storage
   - deterministic prompt augmentation during `run`
   - `before`, `after`, and `on_failure` hooks
   - named `context_sources` in config
   - git branch, commit, push, and PR behavior
2. Verify stage 5 behavior works:
   - signal ingestion during `propagate run`
   - local context population from signal payloads
   - trigger matching and follow-on execution selection
   - clear failures for invalid signal or trigger input
3. Fix any defects directly if you find them.

## Expectations

- Exercise both success and failure paths.
- Confirm signal payload values are stored in the local context bag.
- Confirm trigger matching is deterministic.
- Confirm follow-on executions are selected correctly after a successful source execution.
- Confirm invalid signals and malformed payloads produce clear errors.
- Keep testing within stage 5 scope only. Do not add multi-repo orchestration or DAG scheduling.

## Bootstrap check

Leave the repository targeting stage 6 after testing:

- `config/propagate.yaml` should target `build-stage6`
- `config/prompts/design-stage6.md`, `config/prompts/implement-stage6.md`, `config/prompts/review-stage6.md`, `config/prompts/test-stage6.md`, `config/prompts/refactor-stage6.md`, and `config/prompts/verify-stage6.md` should exist
- those prompts should describe stage-6 multi-repo and DAG orchestration only
