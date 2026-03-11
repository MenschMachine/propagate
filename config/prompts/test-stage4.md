# Stage 4 Test Task

You are testing the stage 4 implementation of Propagate. The runtime should extend stage 3 with git automation while preserving hooks, context sources, the local `.propagate-context` bag, and deterministic prompt augmentation.

## Test goals

1. Verify stage 3 behavior still works:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - `.propagate-context` storage
   - deterministic prompt augmentation during `run`
   - `before`, `after`, and `on_failure` hooks
   - named `context_sources` in config
2. Verify stage 4 behavior works:
   - branch creation and checkout when configured
   - commit creation after successful runs
   - push behavior when configured
   - PR creation when configured
   - commit-message sourcing from a context source
   - dirty-tree rejection before a run starts
3. Fix any defects directly if you find them.

## Expectations

- Exercise both success and failure paths.
- Confirm git automation only runs when configured.
- Confirm dirty working tree is rejected before execution begins.
- Confirm commit messages are sourced correctly from context.
- Confirm push and PR creation failures are reported clearly.
- Keep testing within stage 4 scope only. Do not add signals, propagation triggers, or multi-repo behavior.

## Bootstrap check

Leave the repository targeting stage 5 after testing:

- `config/propagate.yaml` should target `build-stage5`
- `config/prompts/design-stage5.md`, `config/prompts/implement-stage5.md`, `config/prompts/review-stage5.md`, `config/prompts/test-stage5.md`, `config/prompts/refactor-stage5.md`, and `config/prompts/verify-stage5.md` should exist
- those prompts should describe stage-5 signals and propagation triggers only
