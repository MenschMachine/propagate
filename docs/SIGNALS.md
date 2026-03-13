# Signals

Signals are typed events that trigger executions. They carry an optional structured payload — key-value data your sub-tasks can read via the context store.

---

## Overview

A signal has:

- A **name** — identifies which signal is being sent
- A **payload schema** — declares the fields, their types, and whether they are required
- A **payload** — the actual data provided at runtime

Signals are declared in the config, attached to executions, and supplied on the CLI when running.

---

## Declaring signals in config

```yaml
signals:
  deploy:
    payload:
      branch:
        type: string
        required: true
      dry-run:
        type: boolean
        required: false
```

A signal with no payload fields:

```yaml
signals:
  run:
    payload: {}
```

### Payload field options

| Key | Values | Default | Description |
|-----|--------|---------|-------------|
| `type` | `string`, `number`, `boolean`, `list`, `mapping`, `any` | `string` | Expected type of the field value |
| `required` | `true`, `false` | `false` | Whether the field must be present at runtime |

---

## Attaching signals to executions

An execution declares which signals it accepts via the `signals` list:

```yaml
executions:
  deploy-backend:
    repository: backend
    signals: [deploy]
    sub_tasks:
      - id: run
        prompt: ./prompts/deploy.md
```

An execution can accept multiple signals:

```yaml
signals: [deploy, rollback]
```

If exactly one execution accepts the given signal, `--execution` is not needed — the execution is selected automatically.

---

## Supplying a signal at runtime

### Inline payload via `--signal-payload`

Pass payload fields as a YAML or JSON mapping string:

```bash
propagate run --config config/propagate.yaml \
  --signal deploy \
  --signal-payload '{branch: main, dry-run: false}'
```

For signals with no payload, omit `--signal-payload`:

```bash
propagate run --config config/propagate.yaml --signal run
```

### Signal file via `--signal-file`

Write a YAML or JSON file with a `type` key and optional `payload`:

```yaml
# signal.yaml
type: deploy
payload:
  branch: main
  dry-run: false
```

Then pass the file path:

```bash
propagate run --config config/propagate.yaml --signal-file ./signal.yaml
```

`--signal-file` cannot be combined with `--signal` or `--signal-payload`.

---

## Validation

Before any execution starts, the signal payload is validated:

- Unknown fields (not declared in the schema) are rejected
- Fields declared as `required: true` must be present
- Each field value must match its declared type

Errors are reported and the run is aborted before any work begins.

---

## Accessing signal data in sub-tasks

When a signal is active, its data is written into the `:signal` context namespace and available in before/after hooks, on_failure hooks, and prompt templates.

### Available context keys

| Key | Type | Description |
|-----|------|-------------|
| `:signal.type` | string | The signal name, e.g. `deploy` |
| `:signal.source` | string | `cli` or the resolved path of the signal file |
| `:signal.payload` | string | Full payload serialised as a YAML string |
| `:signal.<field>` | string | One key per payload field, value serialised to string |

For `list` and `mapping` fields, the per-field key (`:signal.<field>`) is serialised as YAML. For scalar types it is the plain string representation.

### Reading in hooks

Use `propagate context get` in a before/after hook:

```yaml
before:
  - echo "Deploying branch $(propagate context get :signal.branch)"
  - propagate context dump
```

### Reading in prompt templates

Reference keys directly in the prompt file:

```
Deploy branch {:signal.branch} to production.
Dry run: {:signal.dry-run}
```

---

## Signal context lifecycle

The `:signal` namespace is written once per execution working directory, the first time a sub-task runs within that execution. It is cleared and repopulated on each fresh run. On `--resume`, the signal from the original run is restored and the namespace is not re-initialised for directories that were already populated.

---

## Execution selection rules

| Situation | Behaviour |
|-----------|-----------|
| `--execution` specified | That execution is used; it must accept the signal if one is given |
| Signal given, one execution accepts it | That execution is auto-selected |
| Signal given, multiple executions accept it | Error — specify `--execution` |
| Signal given, no execution accepts it | Error |
| No signal, one execution in config | That execution is used |
| No signal, multiple executions in config | Error — specify `--execution` |

---

## Propagation triggers with signals

A propagation trigger can be conditioned on a signal using `on_signal`:

```yaml
propagation:
  - after: deploy-backend
    run: run-integration-tests
    on_signal: deploy
```

This trigger only fires if the active signal for the run is `deploy`. If `on_signal` is omitted, the trigger fires unconditionally after the `after` execution completes.
