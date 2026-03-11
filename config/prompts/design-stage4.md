# Stage 4 Design Task

You are working inside the Propagate repository. The runtime is now stage 3: it can parse config, execute sequential sub-tasks, manage a local `.propagate-context` bag, inject sorted context values into prompts, run `before` / `after` / `on_failure` hooks, and load configured context sources into reserved `:`-prefixed local context keys.

Your job in this sub-task is to design stage 4: add git automation while preserving the stage 3 runtime model.

## Deliverables

1. Write an implementation-ready design note for stage 4 git automation.
2. Keep the design within stage 4 scope only.
3. Do not implement code in this sub-task unless a tiny clarification edit is unavoidable.

## Stage 4 scope

Stage 4 adds repository-local git automation for successful Propagate runs:

- branch creation and selection
- commit creation after successful sub-tasks
- push support
- PR creation when configured
- commit-message sourcing from a context source

Stage 4 does not add signals, propagation triggers, includes, defaults, repository registries, multi-repo orchestration, or DAG execution.

## Required design decisions

The design note must define:

1. Config shape changes for git automation.
2. When git setup runs relative to the existing hook and agent phases.
3. How branch naming and branch reuse work.
4. How commit messages are sourced, including use of a context source value.
5. How commit, push, and PR creation failures behave.
6. What happens when the working tree is dirty before a run starts.
7. Logging and error handling expectations.
8. The stage boundary: no signals, no multi-repo orchestration.

## Constraints

- Keep the implementation in `propagate.py`
- Python 3.10+
- Use logging, not `print()`
- Use type hints
- Use f-strings
- Keep `PyYAML` as the only external dependency
- Preserve the existing `{prompt_file}` handoff
- Treat hooks and context sources as already implemented

## Current runtime facts

- `config/propagate.yaml` is version `"3"`
- prompt paths resolve relative to the config file
- context is stored in `.propagate-context` under the invocation working directory
- `before`, `after`, and `on_failure` hooks already exist
- context sources already load into keys such as `:source-name`

Keep the design concise and implementation-ready.
