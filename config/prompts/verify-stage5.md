# Stage 5 Verify Task

You are verifying the completed stage 5 state of Propagate. The repository should now contain a working stage-5 runtime built on top of the stage-4 git automation.

## Verify these outcomes

1. `propagate.py` supports:
   - signal ingestion during `propagate run`
   - local context population from signal payloads
   - trigger matching and follow-on execution selection
   - clear failures for invalid signal or trigger input
2. Stage 4 behavior still holds:
   - local context bag storage under `.propagate-context`
   - `propagate context set` and `propagate context get`
   - deterministic `## Context` prompt augmentation
   - prompt-path resolution relative to the config file
   - agent execution from the invocation working directory
   - `before`, `after`, and `on_failure` hooks
   - named `context_sources` loading into `:`-prefixed keys
   - git branch, commit, push, and PR behavior
3. Bootstrap output is advanced to stage 6:
   - `config/propagate.yaml` targets `build-stage6`
   - `config/prompts/design-stage6.md`, `config/prompts/implement-stage6.md`, `config/prompts/review-stage6.md`, `config/prompts/test-stage6.md`, `config/prompts/refactor-stage6.md`, and `config/prompts/verify-stage6.md` exist

## Scope guard

If anything is missing or incorrect, fix it directly. Stay within stage 5 scope only: no multi-repo orchestration and no full DAG scheduling.
