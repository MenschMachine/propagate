# Stage 3 Design Task

You are working inside the Propagate repository. The runtime is now stage 2: it can parse config, execute sequential sub-tasks, manage a local `.propagate-context` bag, and inject sorted context values into prompts during `propagate run`.

Your job in this sub-task is to design stage 3: add hooks and context sources while preserving stage 2 behavior.

## Deliverables

1. Write an implementation-ready design note at `docs/hooks-and-context-sources-stage-3-design.md`.
2. Keep the design within stage 3 scope.
3. Do not implement code in this sub-task unless a tiny clarification edit is unavoidable.

## Stage 3 scope

Stage 3 adds:

- sub-task hooks: `before`, `after`, and `on_failure`
- context-source definitions in config
- hook-driven loading of context sources into the local context bag using keys such as `:openapi-spec`
- validation hooks around the agent call path so command checks can run before and after the agent invocation

Stage 3 still does not include git automation, signals, propagation triggers, includes, defaults, repository orchestration, or DAG execution.

## Required design decisions

The design note must define:

1. Config shape changes for hooks and context sources.
2. How hook commands are parsed and executed.
3. When `before`, `after`, and `on_failure` run in relation to the existing agent command.
4. Failure semantics for hook commands and agent commands.
5. How context sources map to reserved `:`-prefixed keys in `.propagate-context`.
6. How stage 3 uses the existing `propagate context set` command rather than inventing a second storage path.
7. How validation-oriented hooks fit around the agent call without changing stage 2 prompt rendering semantics.
8. How hook execution keeps prompt-path resolution and stage 2 prompt augmentation behavior intact.
9. Logging and error handling expectations.
10. The stage boundary: no git, no signals, no multi-repo work yet.
11. The bootstrap requirement for stage 4: update `config/propagate.yaml` to target stage 4 and create `config/prompts/design-stage4.md`, `config/prompts/implement-stage4.md`, and `config/prompts/review-stage4.md`.

## Full Propagate vision

The full system evolves across these stages:

- Stage 1: config parsing, execution sequencing, agent execution
- Stage 2: local context bag and prompt injection
- Stage 3: hooks and context sources
- Stage 4: git automation
- Stage 5: signals and propagation triggers
- Stage 6: multi-repo and DAG orchestration

The eventual config includes sections such as `version`, `includes`, `defaults`, `repositories`, `context_sources`, `executions`, and `propagation`.

## Constraints

- Keep the implementation in `propagate.py`
- Python 3.10+
- Use logging, not `print()`
- Use type hints
- Use f-strings
- Keep `PyYAML` as the only external dependency
- Continue to pass a temporary prompt file to the configured agent command via `{prompt_file}`
- Preserve stage 2 behavior unless stage 3 explicitly extends it

## Current runtime facts

- `config/propagate.yaml` is version `"2"`
- prompt paths resolve relative to the config file
- context is stored in `.propagate-context` under the invocation working directory
- `propagate context set <key> <value>` and `propagate context get <key>` already exist
- `propagate run` loads local context fresh for each sub-task and appends a deterministic `## Context` section

Use the existing stage 2 design note and current code only as needed. Keep the new design concise but implementation-ready.
