# Stage 5 Design Task

You are working inside the Propagate repository. The runtime is now stage 4: it can parse config, execute sequential sub-tasks, manage a local `.propagate-context` bag, inject sorted context values into prompts, run `before` / `after` / `on_failure` hooks, load configured context sources, and perform repository-local git automation for successful runs.

Your job in this sub-task is to design stage 5: add signals and propagation triggers while preserving the stage 4 runtime model.

## Deliverables

1. Write an implementation-ready design note for stage 5 signal handling and propagation triggers.
2. Keep the design within stage 5 scope only.
3. Do not implement code in this sub-task unless a tiny clarification edit is unavoidable.

## Stage 5 scope

Stage 5 adds:

- signal definitions that describe why an execution should run
- propagation trigger definitions that connect one execution's outcome to another execution
- runtime handling for manual and file-based signal inputs
- context population from signal payloads for downstream prompts

Stage 5 still does not add multi-repository orchestration, repository registries, DAG scheduling across repos, parallel execution, or stage 6 coordination.

## Required design decisions

The design note must define:

1. Config shape changes for signals and propagation triggers.
2. How a signal is supplied to `propagate run`.
3. How trigger matching works relative to the existing execution model.
4. What signal payload fields are stored in the local context bag.
5. How propagation triggers enqueue or select follow-on executions without adding full DAG orchestration.
6. Failure behavior for invalid signals, missing trigger targets, and malformed payloads.
7. Logging and error handling expectations.
8. The stage boundary: no multi-repo execution and no full DAG scheduler yet.
9. The bootstrap requirement for stage 6: update `config/propagate.yaml` to target stage 6 and create the next prompt trio.

## Constraints

- Keep the implementation in `propagate.py`
- Python 3.10+
- Use logging, not `print()`
- Use type hints
- Use f-strings
- Keep `PyYAML` as the only external dependency
- Preserve the existing `{prompt_file}` handoff
- Treat hooks, context sources, and git automation as already implemented

## Current runtime facts

- `config/propagate.yaml` is version `"4"`
- prompt paths resolve relative to the config file
- context is stored in `.propagate-context` under the invocation working directory
- `before`, `after`, and `on_failure` hooks already exist
- context sources already load into keys such as `:source-name`
- git automation can create branches, commit changes, optionally push, and optionally create PRs

Keep the design concise and implementation-ready.
