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

### Including signals from external files

Signal definitions can be loaded from external YAML files using the `include` key. This keeps reusable signal sets (e.g. GitHub webhook signals) in separate files and avoids duplication across configs. Paths are relative to the config file directory.

Single file:

```yaml
signals:
  include: includes/github-signals.yaml
  run:
    payload: {}
```

Multiple files:

```yaml
signals:
  include:
    - includes/github-signals.yaml
    - includes/deploy-signals.yaml
  run:
    payload: {}
```

The included file must be a YAML mapping of signal definitions (same format as inline signals):

```yaml
# includes/github-signals.yaml
pull_request.labeled:
  payload:
    repository:
      type: string
      required: true
    label:
      type: string
      required: true
```

Duplicate signal names between included files and inline definitions (or between multiple included files) are rejected.

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

Each entry can be a plain string or a mapping with `signal` and optional `when` for payload filtering (see [Payload filtering with `when`](#payload-filtering-with-when)):

```yaml
signals:
  - signal: pull_request.labeled
    when:
      label: "deploy"
  - run
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

## Payload filtering with `when`

You can filter on signal payload values using a `when` clause. This enables multiple executions to listen to the same signal but activate only when specific payload fields match.

### On execution signals

```yaml
executions:
  deploy-frontend:
    repository: frontend
    signals:
      - signal: pull_request.labeled
        when:
          label: "deploy"
      - run                          # plain string still works
    sub_tasks:
      - id: deploy
        prompt: ./prompts/deploy.md
```

The execution only activates for `pull_request.labeled` when the payload's `label` field equals `"deploy"`. Plain string entries (like `run`) continue to work and match without any payload filtering.

### On propagation triggers

```yaml
propagation:
  triggers:
    - after: test-backend
      run: deploy-frontend
      on_signal: pull_request.labeled
      when:
        label: "deploy"
```

The trigger only fires when `pull_request.labeled` is the active signal **and** the payload's `label` field equals `"deploy"`. `when` requires `on_signal` to be set.

### Matching rules

- All fields in `when` must match exactly (logical AND)
- Missing payload fields do not match
- `when` with no fields (`when: {}`) matches any payload
- If `when` is omitted, the signal matches regardless of payload

---

## State checking with `check`

Propagation triggers with `on_signal` + `when` normally wait for an external webhook event. But the condition described by `when` may already be true (e.g., a PR already has the required label). Instead of waiting indefinitely, you can add a `check` command to the signal definition. The scheduler runs this command — templated with the trigger's `when` values — before waiting. If it exits 0, the condition is already met and the trigger fires immediately.

### Defining a check command

Add a `check` string to the signal definition. Use `{field_name}` placeholders that correspond to keys in the trigger's `when` clause:

```yaml
signals:
  pull_request.labeled:
    payload:
      repository: { type: string, required: true }
      pr_number: { type: number, required: true }
      label: { type: string, required: true }
    check: "gh pr view {pr_number} --repo {repository} --json labels --jq '.labels[].name' | grep -q '^{label}$'"
```

### How it works

1. When the scheduler has no runnable executions, it checks all pending signal triggers (those with `on_signal` + `when` where the target execution is not yet active)
2. For each pending trigger, if the signal definition has a `check` command:
   - All `{placeholder}` names in the command must have corresponding keys in `when` — otherwise the check is skipped
   - Each `when` value is shell-escaped via `shlex.quote()` before substitution
   - The command runs via `subprocess.run(shell=True)`
3. If the command exits 0: the condition is already met. A synthetic signal is created with the `when` values as payload, and matching triggers are activated
4. If the command exits non-zero or raises an `OSError`: the condition is not met, and the scheduler continues to wait for a real webhook event

### Example

```yaml
signals:
  pull_request.labeled:
    payload:
      repository: { type: string, required: true }
      label: { type: string, required: true }
    check: "gh pr list --repo {repository} --label {label} --state open --json number --jq 'length > 0'"

executions:
  build:
    repository: app
    sub_tasks:
      - id: compile
        prompt: ./prompts/build.md

  deploy:
    repository: app
    sub_tasks:
      - id: ship
        prompt: ./prompts/deploy.md

propagation:
  triggers:
    - after: build
      run: deploy
      on_signal: pull_request.labeled
      when:
        repository: "myorg/myrepo"
        label: "deploy"
```

After `build` completes, the scheduler runs the check command. If a PR with the `deploy` label already exists, `deploy` is activated immediately without waiting for a webhook.

### Limitations

- `check` only runs for triggers that have both `on_signal` and `when` — triggers without `when` cannot template the command
- If the check command has placeholders not present in `when`, it is silently skipped
- A failed check (non-zero exit) is retried on subsequent scheduler iterations until it passes or a real webhook arrives
- A successful check (exit 0) is not re-run for the same trigger

---

## Propagation triggers with signals

A propagation trigger can be conditioned on a signal using `on_signal`:

```yaml
propagation:
  triggers:
    - after: deploy-backend
      run: run-integration-tests
      on_signal: deploy
```

This trigger only fires if the active signal for the run is `deploy`. If `on_signal` is omitted, the trigger fires unconditionally after the `after` execution completes.

---

## Signal-gated sub-tasks

Sub-tasks can wait for signals within an execution using `wait_for_signal` and `routes`. This enables review loops and approval gates without separate executions or propagation triggers.

```yaml
sub_tasks:
  - id: code
    prompt: ./prompts/implement.md
  - id: wait-for-verdict
    wait_for_signal: pull_request.labeled
    routes:
      - when: { label: "changes_required" }
        goto: code
      - when: { label: "approved" }
        continue: true
```

When the sub-task runner reaches a `wait_for_signal` task, it blocks on the ZMQ socket until a matching signal arrives. The signal payload is matched against each route's `when` clause. If a route with `goto` matches, execution jumps back to that sub-task (clearing completed state for all tasks from the target onward). If a route with `continue` matches, execution proceeds to the next sub-task.

Signal-gated sub-tasks require `propagate serve` (they need a ZMQ socket). The `:signal.*` context keys are updated with the new signal payload when a route matches.

See [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) for full syntax.

---

## External signal delivery

Signals can be sent to a running propagate instance from outside the process. When the scheduler has no runnable executions but signal-gated propagation triggers exist, it waits for external signals instead of exiting.

### One-shot vs serve mode

- **`propagate run`** — opens the ZMQ socket only when signal-gated propagation triggers exist. Runs the DAG once and exits.
- **`propagate serve`** — opens the ZMQ socket unconditionally and stays alive, processing each incoming signal as a separate DAG run. See [SERVE.md](SERVE.md) for details.

### How it works

When a config has propagation triggers with `on_signal`, the `propagate run` command opens a ZeroMQ IPC socket at `ipc:///tmp/propagate-{hash}.sock` (where `{hash}` is derived from the full resolved config path). The scheduler polls this socket for incoming signals between executions and blocks on it when waiting. The `propagate serve` command uses the same socket but always binds it.

### Sending a signal with `send-signal`

```bash
propagate send-signal --config config/propagate.yaml \
  --signal deploy \
  --signal-payload '{branch: main}'
```

Or via signal file:

```bash
propagate send-signal --config config/propagate.yaml \
  --signal-file ./signal.yaml
```

The `--config` path must match the one used by the running `propagate run` instance — it determines the socket address.

The signal is validated against the config's signal definitions before sending. Unknown signal types, missing required fields, and type mismatches are rejected.

### Example: wait for external approval

```yaml
signals:
  approved:
    payload: {}

executions:
  build:
    repository: app
    sub_tasks:
      - id: compile
        prompt: ./prompts/build.md

  deploy:
    repository: app
    sub_tasks:
      - id: ship
        prompt: ./prompts/deploy.md

propagation:
  triggers:
    - after: build
      run: deploy
      on_signal: approved
```

```bash
# Terminal 1: start the run — builds, then waits for "approved" signal
propagate run --config config/propagate.yaml --execution build

# Terminal 2: send the signal when ready
propagate send-signal --config config/propagate.yaml --signal approved
```
