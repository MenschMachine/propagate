# Stage 3 Verify Task

You are verifying the completed stage 3 state of Propagate. The repository should now contain a working stage-3 runtime built on top of the stage-2 local context bag.

## Verify these outcomes

1. `propagate.py` supports:
   - sub-task `before`, `after`, and `on_failure` hooks
   - named `context_sources` in config
   - hook-driven loading into `.propagate-context` using `:source-name` keys
   - validation-oriented hooks around agent calls
2. Stage 2 behavior still holds:
   - local context bag storage under `.propagate-context`
   - `propagate context set` and `propagate context get`
   - deterministic `## Context` prompt augmentation
   - prompt-path resolution relative to the config file
   - agent execution from the invocation working directory
3. Bootstrap output is advanced to stage 4:
   - `config/propagate.yaml` targets `build-stage4`
   - `config/prompts/design-stage4.md`, `config/prompts/implement-stage4.md`, and `config/prompts/review-stage4.md` exist

## Scope guard

If anything is missing or incorrect, fix it directly. Stay within stage 3 scope only: no git implementation yet, no signals, and no multi-repo orchestration.
