# Stage 4 Review Task

You are reviewing the stage 4 implementation of Propagate. The repository started from stage 3 and should now include git automation on top of hooks, context sources, the local context bag, and prompt injection.

## Review goals

1. Verify stage 3 behavior still works:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - hook execution order
   - context-source loading into reserved `:`-prefixed keys
   - deterministic prompt augmentation
2. Verify stage 4 additions work:
   - branch creation and checkout
   - commit creation after successful runs
   - push behavior when configured
   - PR creation when configured
   - commit-message sourcing from context
3. Verify the bootstrap chain was advanced:
   - `config/propagate.yaml` should now target building stage 5
   - the stage 5 prompt trio should exist and focus on signals and propagation triggers
4. Fix problems directly if you find them.

## Review checklist

- Existing context bag semantics still hold.
- Hooks and context sources still behave correctly.
- Git automation runs only in the intended stage 4 paths.
- Git failures are clear and non-silent.
- The implementation stays within stage 4 scope and does not partially add multi-repo orchestration.

## Stage boundary

The full Propagate roadmap is:

- Stage 1: config parsing, execution sequencing, agent execution
- Stage 2: local context bag and prompt injection
- Stage 3: hooks and context sources
- Stage 4: git automation
- Stage 5: signals and propagation triggers
- Stage 6: multi-repo and DAG orchestration

This review is only about stage 4 correctness and preserving the stage 3 foundation.
