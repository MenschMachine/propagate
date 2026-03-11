# Stage 4 Verify Task

You are verifying the completed stage 4 state of Propagate. The repository should now contain a working stage-4 runtime built on top of the stage-3 hooks and context sources.

## Verify these outcomes

1. `propagate.py` supports:
   - branch creation and checkout when configured
   - commit creation after successful runs
   - push behavior when configured
   - PR creation when configured
   - commit-message sourcing from a context source
   - dirty-tree rejection before a run starts
2. Stage 3 behavior still holds:
   - local context bag storage under `.propagate-context`
   - `propagate context set` and `propagate context get`
   - deterministic `## Context` prompt augmentation
   - prompt-path resolution relative to the config file
   - agent execution from the invocation working directory
   - `before`, `after`, and `on_failure` hooks
   - named `context_sources` loading into `:`-prefixed keys
3. Bootstrap output is advanced to stage 5:
   - `config/propagate.yaml` targets `build-stage5`
   - `config/prompts/design-stage5.md`, `config/prompts/implement-stage5.md`, `config/prompts/review-stage5.md`, `config/prompts/test-stage5.md`, `config/prompts/refactor-stage5.md`, and `config/prompts/verify-stage5.md` exist

## Scope guard

If anything is missing or incorrect, fix it directly. Stay within stage 4 scope only: no signals, no propagation triggers, and no multi-repo orchestration.
