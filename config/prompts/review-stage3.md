# Stage 3 Review Task

You are reviewing the stage 3 implementation of Propagate. The repository started from stage 2 and should now include hooks and context sources on top of the existing local context bag.

## Review goals

1. Verify stage 2 behavior still works:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - `.propagate-context` storage
   - deterministic prompt augmentation
2. Verify stage 3 additions work:
   - sub-task hooks: `before`, `after`, `on_failure`
   - config parsing for hooks and context sources
   - hook-driven loading of context sources into reserved `:`-prefixed context keys
   - validation-oriented hooks around the agent execution path
3. Verify the bootstrap chain was advanced:
   - `config/propagate.yaml` should now target building stage 4
   - `config/prompts/design-stage4.md`, `config/prompts/implement-stage4.md`, and `config/prompts/review-stage4.md` should exist and describe git automation
4. Fix problems directly if you find them.

## Review checklist

- Existing context bag semantics still hold.
- Hook execution order is correct and deterministic.
- Hook and context-source failures are clear and non-silent.
- Validation hooks run only in the intended phases around agent execution.
- `on_failure` runs only on the intended failure path.
- Prompt augmentation still uses the local context bag contents actually present at sub-task execution time.
- The implementation stays within stage 3 scope and does not partially add git or signal behavior.

## Stage boundary

The full Propagate roadmap is:

- Stage 1: config parsing, execution sequencing, agent execution
- Stage 2: local context bag and prompt injection
- Stage 3: hooks and context sources
- Stage 4: git automation
- Stage 5: signals and propagation triggers
- Stage 6: multi-repo and DAG orchestration

This review is only about stage 3 correctness and preserving the stage 2 foundation.
