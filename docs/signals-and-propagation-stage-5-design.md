# Signals And Propagation Stage 5 Design

## Scope

Stage 5 adds repository-local signal handling on top of the stage 4 runtime:

- config-defined signal types
- optional signal-aware execution selection
- manual and file-based signal input for `propagate run`
- signal payload storage in `.propagate-context`
- repository-local propagation triggers that enqueue follow-on executions after success

Stage 5 keeps the stage 4 runtime model intact:

- each execution still runs its sub-tasks sequentially
- hooks, context sources, and prompt augmentation keep their current meaning
- git automation still wraps a single execution and completes before triggers are considered
- all work still happens in the repository at `Path.cwd()`

Stage 5 does not add repository registries, cross-repository execution, parallelism, retries, or a general DAG scheduler.

## Config Shape

Bump the schema marker to `version: "5"` and require that exact value in `load_config()`.

Add three stage-5 config changes:

```yaml
version: "5"

signals:
  repo-change:
    payload:
      branch:
        type: string
        required: true
      files:
        type: list
      urgent:
        type: boolean

executions:
  build-stage5:
    signals:
      - repo-change
    sub_tasks:
      - id: design
        prompt: ./prompts/design-stage5.md

propagation:
  triggers:
    - after: build-stage5
      on_signal: repo-change
      run: verify-stage5
```

Validation rules:

- `signals` is optional. If present, it must be a non-empty mapping.
- Each signal name must validate with the same name rules used for context-source names.
- Each signal definition is a mapping with one required field for stage 5: `payload`.
- `payload` must be a mapping. It may be empty when a signal has no defined fields.
- Each payload field name must validate as a context-key suffix such as `branch`, `ticket.id`, or `changed-files`.
- Each payload field definition is a mapping with:
  - optional `type`, default `string`
  - optional `required`, default `false`
- Supported field types are `string`, `number`, `boolean`, `list`, `mapping`, and `any`.
- `executions.<name>.signals` is optional. If present, it must be a non-empty list of unique signal names defined in `signals`.
- `propagation` is optional. If present, it must be a mapping with required key `triggers`.
- `propagation.triggers` must be a non-empty list.
- Each trigger is a mapping with required keys `after` and `run`, plus optional key `on_signal`.
- `after` and `run` must reference existing execution names.
- `on_signal`, when provided, must reference an existing signal name.

Stage 5 intentionally does not add signal defaults, payload templates, emitted signals, trigger conditions over payload contents, trigger fan-in, trigger retries, or repository references.

## Supplying A Signal To `propagate run`

Extend the `run` command with these options:

- `--signal <name>`
- `--signal-payload <yaml-or-json-mapping>`
- `--signal-file <path>`

Rules:

- `--signal-file` is mutually exclusive with `--signal` and `--signal-payload`.
- `--signal-payload` requires `--signal`.
- `--signal` without `--signal-payload` means an empty payload mapping.
- `--signal-file` points to a YAML or JSON document with shape:

```yaml
type: repo-change
payload:
  branch: main
  files:
    - propagate.py
```

Manual input example:

```sh
propagate run \
  --config config/propagate.yaml \
  --signal repo-change \
  --signal-payload '{"branch":"main","files":["propagate.py"]}'
```

Validation happens before any execution, hook, or git preparation:

- the signal type must exist in `signals`
- the payload must parse as a mapping
- all required fields must be present
- provided fields must match the declared field types
- unknown payload fields fail fast in stage 5

If no signal is supplied, `propagate run` keeps the stage 4 behavior.

## Execution Selection

Stage 4 selection remains the default:

- `--execution <name>` still selects that execution directly
- without `--execution`, a config with exactly one execution still runs that execution

Stage 5 adds one signal-aware selection path:

- when `--execution` is omitted and an active signal is present, find executions whose optional `signals` list contains that signal
- if exactly one execution matches, select it
- if zero executions match, raise `PropagateError`
- if multiple executions match, raise `PropagateError` and require `--execution`

If `--execution` is provided and the selected execution declares `signals`, the active signal must be listed there. If the execution does not declare `signals`, it may still be run manually with or without a signal.

This keeps direct execution selection intact while letting stage 5 route a signal into one repository-local execution when the config is unambiguous.

## Signal Context Storage

Signal data reuses the existing local context bag. Do not add a second store.

Before the first execution starts:

1. Remove any existing reserved keys in the `:signal` namespace from `.propagate-context`.
2. If there is no active signal, stop there.
3. Write the validated signal into reserved keys.

Stored keys:

- `:signal.type` with the signal name
- `:signal.source` with `cli` or the resolved signal-file path
- `:signal.payload` with the full payload serialized via `yaml.safe_dump(..., sort_keys=True)`
- `:signal.<field-name>` for every top-level payload field

Value rendering rules:

- `string`, `number`, and `boolean` fields are stored as their string form
- `list` and `mapping` fields are stored as deterministic YAML via `yaml.safe_dump(..., sort_keys=True)`
- `any` fields use scalar stringification for scalars and deterministic YAML for lists or mappings

Only top-level payload fields get their own keys in stage 5. Nested values remain available inside `:signal.payload` or in the serialized value of their top-level field. Stage 5 does not flatten arbitrarily deep structures into many context files.

Clearing the `:signal` namespace first prevents stale payload values from earlier runs from leaking into later prompts.

## Trigger Matching

Propagation triggers are execution-level and success-only.

Trigger evaluation rules:

1. Run the selected execution using the existing stage 4 path.
2. Treat the execution as successful only after all sub-tasks succeed and any configured git commit, push, and PR steps also succeed.
3. Evaluate triggers only after that full execution success.
4. Consider triggers in the order they appear in `propagation.triggers`.
5. A trigger matches when:
   - `trigger.after == completed_execution.name`
   - and `trigger.on_signal` is absent, or it equals the active signal type

No triggers run when the source execution fails. Stage 5 does not trigger from sub-task boundaries, partial success, or failure outcomes.

## Follow-On Execution Queue

Stage 5 adds a simple FIFO queue, not a DAG planner.

Runtime model:

- start with one selected execution in the queue
- pop the next execution, run it fully, then evaluate matching triggers
- append each matching trigger target to the queue in config order
- skip enqueueing a target that is already queued or has already completed in the current `propagate run`

This gives deterministic repository-local propagation while preventing trivial trigger loops from running forever. Cycles are not scheduled repeatedly; they are skipped once the target is already seen.

Stage 5 does not:

- precompute a full graph
- detect or optimize fan-out shapes beyond queue order
- run executions in parallel
- coordinate across repositories

## Failure Behavior

Invalid config fails during `load_config()`:

- unsupported `signals`, `executions.<name>.signals`, or `propagation` shapes
- unknown signal names in execution signal lists
- unknown execution names in triggers
- unknown signal names in `trigger.on_signal`
- invalid payload field definitions or unsupported field types

Invalid runtime signal input fails before the first execution starts:

- unknown signal type from CLI or file
- unreadable signal file
- malformed YAML or JSON
- payload document that is not a mapping
- missing required fields
- unknown extra fields
- type mismatches

Propagation failures behave like execution failures:

- if a queued follow-on execution name is somehow missing at runtime, raise `PropagateError`
- if a follow-on execution fails, stop the queue immediately and return a failing run
- do not roll back prior successful executions, context writes, commits, pushes, or PRs

Malformed payload values never reach prompt augmentation. The run stops before hook execution or branch setup.

## Logging And Errors

Use `logging`, not `print()`.

`INFO` logs should cover:

- whether a signal was supplied
- active signal type and source, but not payload values
- signal-based execution auto-selection when it happens
- clearing and repopulating the `:signal` namespace
- trigger evaluation after each successful execution
- each matched trigger
- each enqueue skip caused by duplicate or already-completed targets
- queue start and queued execution start

Do not log:

- prompt contents
- signal payload contents
- stored context values
- raw subprocess stdout on success

Representative errors:

- `Signal 'repo-change' payload is missing required field 'branch'.`
- `Signal 'repo-change' payload field 'files' must be a list.`
- `Signal file '/path/to/signal.yaml' must define a mapping with key 'type'.`
- `No execution accepts signal 'repo-change'.`
- `Multiple executions accept signal 'repo-change'; specify --execution.`
- `Execution 'verify-stage5' was enqueued by propagation but is not defined.`

## Implementation Shape

Keep the change in `propagate.py` with small dataclasses and helpers.

Suggested additions:

- `SignalFieldConfig`
- `SignalConfig`
- `PropagationTriggerConfig`
- `ActiveSignal`
- extend `ExecutionConfig` with `signals`
- extend `Config` with `signals` and `propagation_triggers`
- extend `RuntimeContext` with `active_signal`
- `parse_signal_configs(...)`
- `parse_signal_field_config(...)`
- `parse_propagation_triggers(...)`
- `parse_active_signal(...)`
- `validate_signal_payload(...)`
- `clear_signal_context_namespace(...)`
- `store_active_signal_context(...)`
- `select_initial_execution(...)`
- `run_execution_queue(...)`
- `enqueue_matching_triggers(...)`

The important boundary is behavioral:

- stage 4 sub-task, hook, context-source, and git behavior remain unchanged inside one execution
- stage 5 adds signal validation and a small queue around execution selection
- signal payload values land in the same `.propagate-context` bag already used by prompts and hooks

## Stage Boundary

Stage 5 explicitly does not add:

- repository registries
- named repositories on executions or triggers
- cross-repository context sharing
- DAG planning across multiple repositories
- parallel execution
- retries, debounce logic, or background workers
- execution-output-derived signal emission

Unsupported multi-repo or scheduler-oriented keys should continue to fail validation clearly rather than being partially implemented.

## Bootstrap Output For Stage 6

The stage 5 implementation should advance the self-hosting chain:

- update `config/propagate.yaml` to target `build-stage6`
- bump that config to `version: "5"`
- rename the execution to `build-stage6`
- point its sub-task prompts to:
  - `./prompts/design-stage6.md`
  - `./prompts/implement-stage6.md`
  - `./prompts/review-stage6.md`
  - `./prompts/test-stage6.md`
  - `./prompts/refactor-stage6.md`
  - `./prompts/verify-stage6.md`
- create those six prompt files

Those stage 6 prompts should ask the next run to add repository registries, repository selection, and DAG orchestration while preserving stage 5 signals and propagation. They should stay inside final-stage scope and should not introduce a stage 7 bootstrap target.
