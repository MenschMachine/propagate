# Stage 5 Review Task

You are reviewing the stage 5 implementation of Propagate. The repository started from stage 4 and should now include signals and propagation triggers on top of hooks, context sources, the local context bag, prompt injection, and git automation.

## Review goals

1. Verify stage 4 behavior still works:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - hook execution order
   - context-source loading into reserved `:`-prefixed keys
   - deterministic prompt augmentation
   - git branch, commit, push, and PR behavior
2. Verify stage 5 additions work:
   - signal ingestion during `propagate run`
   - local context population from signal payloads
   - trigger matching and follow-on execution selection
   - clear failures for invalid signal or trigger input
3. Verify the bootstrap chain was advanced:
   - `config/propagate.yaml` should now target building stage 6
   - the stage 6 prompt trio should exist and focus on multi-repo and DAG orchestration
4. Fix problems directly if you find them.

## Review checklist

- Existing context bag semantics still hold.
- Hooks and context sources still behave correctly.
- Git automation still runs only in the intended stage 4 and later paths.
- Signal handling and trigger evaluation are deterministic and local to the repository.
- Failures are clear and non-silent.
- The implementation stays within stage 5 scope and does not partially add stage 6 orchestration.

## Stage boundary

The full Propagate roadmap is:

- Stage 1: config parsing, execution sequencing, agent execution
- Stage 2: local context bag and prompt injection
- Stage 3: hooks and context sources
- Stage 4: git automation
- Stage 5: signals and propagation triggers
- Stage 6: multi-repo and DAG orchestration

This review is only about stage 5 correctness and preserving the stage 4 foundation.
