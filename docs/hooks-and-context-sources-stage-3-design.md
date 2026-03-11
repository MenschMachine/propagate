# Hooks And Context Sources Stage 3 Design

## Scope

Stage 3 extends the stage 2 runtime with:

- per-sub-task `before`, `after`, and `on_failure` hooks
- top-level `context_sources` definitions in config
- hook-driven loading of context-source output into the existing local context bag under reserved `:`-prefixed keys

Stage 3 does not add git automation, signals, propagation triggers, includes, defaults, repositories, task-scoped context, global context, or DAG execution. The implementation stays in `propagate.py`, uses Python 3.10+, `PyYAML`, logging, type hints, f-strings, and preserves the existing `{prompt_file}` agent handoff.

## Config changes

Bump the schema marker to `version: "3"` and require that exact version in `load_config()`.

Add one new top-level section:

```yaml
context_sources:
  openapi-spec:
    command: cat api/openapi.yaml
  breaking-changes:
    command: ./scripts/detect-breaking-changes.sh --format=markdown
```

Add three optional fields to each sub-task:

```yaml
executions:
  build-stage4:
    sub_tasks:
      - id: design
        prompt: ./prompts/design-stage4.md
        before:
          - :openapi-spec
        after:
          - python -m pytest
        on_failure:
          - ./scripts/report-failure.sh design
```

Shape rules:

- `context_sources` is optional. If present, it must be a non-empty mapping.
- Each context-source name must be a non-empty string and must validate as a context key suffix. `openapi-spec` is valid; `:openapi-spec` is not.
- Each context source is a mapping with exactly one required field for stage 3: `command`.
- `command` must be a non-empty string.
- `before`, `after`, and `on_failure` are optional lists of non-empty strings.
- Prompt paths continue to resolve relative to the config file exactly as in stage 2.
- All hook commands and context-source commands run in the invocation working directory (`Path.cwd()`), not relative to the config file.

The config stays intentionally narrow. Stage 3 does not add hook-level environment blocks, per-source working directories, retries, timeouts, includes, or repository references.

## Hook command model

Each hook item is parsed as one of two action types:

1. A context-source reference if the entire string starts with `:`
2. A raw shell command otherwise

Examples:

- `:openapi-spec` means: run the `openapi-spec` context source and store its stdout under `.propagate-context/:openapi-spec`
- `python -m pytest` means: run that shell command directly

Parsing rules:

- A `:` action must validate as a full context key with `validate_context_key()`.
- The referenced source name is the key without the leading `:`.
- The source name must exist in `config.context_sources`.
- A missing source is a configuration error surfaced as `PropagateError`.
- Non-`:` hook items are passed through unchanged to `subprocess.run(..., shell=True, cwd=working_dir, check=True)`.

This design keeps the hook syntax small while making context loading explicit and readable in config.

## Context-source execution

Context sources are not a second storage mechanism. They are only a way to produce values that are then written into the existing stage 2 bag.

Execution flow for a `:name` hook item:

1. Resolve `name` in `config.context_sources`.
2. Run the configured source command with `shell=True`, `cwd=working_dir`, `check=True`, `capture_output=True`, and `text=True`.
3. Take `stdout` exactly as returned.
4. Store it via the existing context-write path using key `:name`.

Implementation requirement:

- Reuse the existing `context_set_command()` / `write_context_value()` path rather than inventing a second store or writing directly to some other file.
- The stored filename is literally `.propagate-context/:name`, matching the reserved-key convention introduced in stage 2.
- No trimming, parsing, or Markdown wrapping is applied to the captured stdout before storage.

Because stage 2 already reloads `.propagate-context` per sub-task, later sub-tasks automatically see any context values written by earlier hooks.

## Sub-task execution order

Stage 2 currently does:

1. Read prompt file
2. Load local context
3. Append `## Context`
4. Write temporary prompt file
5. Run agent command

Stage 3 changes the order to:

1. Log sub-task start using the resolved prompt path
2. Run `before` hook actions in order
3. Read the prompt file from the already-resolved stage 2 prompt path
4. Load local context from `.propagate-context`
5. Append the deterministic `## Context` section
6. Write the temporary prompt file
7. Run the agent command with `{prompt_file}` substitution
8. Run `after` hook actions in order
9. Log sub-task completion

Why `before` runs first:

- it can populate `:source` values before prompt augmentation
- stage 2 prompt rendering remains unchanged once context has been loaded
- prompt-path resolution remains a config-parse concern, not a hook concern

`on_failure` is not part of the success path. It runs only after a failed `before`, agent, or `after` phase as described below.

## Failure semantics

### `before`

- `before` actions run sequentially.
- The first failing `before` action stops the remaining `before` actions.
- The agent command does not run.
- The `after` hook does not run.
- `on_failure` runs.

### Agent command

- The agent still runs once per sub-task, after prompt augmentation.
- If the agent command fails, `after` does not run.
- `on_failure` runs.

### `after`

- `after` actions run only if the agent command succeeded.
- They run sequentially.
- The first failing `after` action stops the remaining `after` actions.
- The sub-task is considered failed.
- `on_failure` runs.

### `on_failure`

- `on_failure` actions run sequentially after a failed `before`, agent, or `after` phase.
- `on_failure` does not run on success.
- `on_failure` is best-effort as a phase, but not silent:
  if an `on_failure` action fails, include that fact in the final raised `PropagateError`.
- `on_failure` never converts a failed sub-task into a successful one.

### Non-command failures

Prompt read errors, temporary prompt file creation failures, and context directory IO failures should continue to raise `PropagateError` directly, as in stage 2. Stage 3 does not need a second recovery model for those cases.

### Execution-level effect

Any sub-task failure still aborts the overall execution immediately, matching stage 2 behavior.

## Error messages

Errors should identify:

- sub-task id
- phase: `before`, `agent`, `after`, or `on_failure`
- hook index when relevant
- exit code for subprocess failures when available
- context-source name for source-loading failures

Representative messages:

- `Before hook #1 failed for sub-task 'design' with exit code 1.`
- `Context source 'openapi-spec' failed for sub-task 'design' with exit code 1.`
- `Agent command failed for sub-task 'design' with exit code 1.`
- `After hook #2 failed for sub-task 'design' with exit code 1; on_failure hook #1 also failed with exit code 1.`

## Logging

Keep the stage 2 logging model and extend it conservatively:

- Keep existing execution start and completion `INFO` logs.
- Keep existing context-load logging before prompt augmentation.
- Log the start of each hook phase only when that phase has actions.
- Log each hook action at `INFO` with sub-task id, phase, and ordinal number.
- For context-source actions, log the source name but never the captured value.
- Do not log prompt contents, context values, or captured stdout/stderr on success.
- Keep temporary prompt cleanup best-effort with a warning on failure.

Suggested `INFO` examples:

- `Running before hook 1/2 for sub-task 'design'.`
- `Loading context source 'openapi-spec' for sub-task 'design'.`
- `Running after hook 1/1 for sub-task 'design'.`

## Implementation shape

Keep the change in `propagate.py` with small helpers. One straightforward shape is:

- extend `SubTaskConfig` with `before`, `after`, and `on_failure`
- add `ContextSourceConfig`
- extend `Config` with `context_sources`
- add `parse_context_sources()`
- add `parse_hook_actions()`
- add `run_hook_phase(...)`
- add `run_hook_action(...)`
- add `run_context_source(...)`
- keep `append_context_to_prompt()` and local-context loading unchanged

The important boundary is behavioral, not structural:

- prompt-path resolution stays in config parsing
- prompt augmentation still reads the local bag right before the agent call
- context-source output lands in the same bag read by stage 2
- validation hooks wrap the existing agent call path without changing how prompts are read, augmented, or handed off

## Stage boundary

Stage 3 explicitly does not add:

- git branch creation, commits, pushes, or PR creation
- repository selection or multi-repo working directories
- signals, labels, triggers, or `propagation`
- includes or defaults
- task-scoped or global context
- retries, timeouts, or parallel execution

Unsupported config keys outside the stage 3 additions should continue to fail validation clearly rather than being partially implemented.

## Bootstrap output for stage 4

The stage 3 implementation should also advance the self-hosting chain:

- update `config/propagate.yaml` to target stage 4
- bump that config to `version: "3"`
- rename the execution to `build-stage4`
- point its sub-task prompts to:
  - `./prompts/design-stage4.md`
  - `./prompts/implement-stage4.md`
  - `./prompts/review-stage4.md`
- create those three prompt files

Those stage 4 prompts should ask the next run to add git automation only:

- branch creation and selection
- commit and push after successful sub-tasks
- PR creation when needed
- commit-message sourcing from a context source

They should explicitly treat hooks and context sources as already available and should not expand into signals or multi-repo orchestration yet.
