# Stage 3 Test Task

You are testing the stage 3 implementation of Propagate. The runtime should extend stage 2 with hooks and named context sources while preserving the local `.propagate-context` bag and deterministic prompt augmentation.

## Test goals

1. Verify stage 2 behavior still works:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - `.propagate-context` storage
   - deterministic prompt augmentation during `run`
2. Verify stage 3 behavior works:
   - `before`, `after`, and `on_failure` hooks
   - named `context_sources` in config
   - hook-driven loading into `.propagate-context` via keys like `:source-name`
   - validation-oriented hooks around the agent execution path
3. Fix any defects directly if you find them.

## Expectations

- Exercise both success and failure paths.
- Confirm later sub-tasks see context values produced by earlier hooks.
- Confirm `on_failure` runs only after a failed `before`, agent, or `after` phase.
- Confirm context-source output is stored literally in `.propagate-context/:source-name`.
- Keep testing within stage 3 scope only. Do not add git, signals, or multi-repo behavior.

## Bootstrap check

Leave the repository targeting stage 4 after testing:

- `config/propagate.yaml` should target `build-stage4`
- `config/prompts/design-stage4.md`, `config/prompts/implement-stage4.md`, and `config/prompts/review-stage4.md` should exist
- those prompts should describe stage-4 git automation only
