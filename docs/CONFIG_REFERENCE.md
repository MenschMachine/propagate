# Configuration Reference

Propagate uses a YAML configuration file to define the entire execution DAG. This document covers every available
option.

## Top-Level Structure

```yaml
version: "6"              # Required
agent:                     # Required
  command: "..."
repositories:              # Required
  name: { ... }
context_sources:           # Optional
  name: { ... }
signals:                   # Optional
  name: { ... }
executions:                # Required
  name: { ... }
propagation:               # Optional
  triggers: [...]
```

All keys not listed above are rejected.

---

## `version`

**Required.** Must be the string `"6"`.

```yaml
version: "6"
```

---

## `agent`

Defines the shell command used to invoke the agent for each sub-task.

```yaml
agent:
  command: "claude -p {prompt_file}"
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | Yes | Shell command to run. Must contain the `{prompt_file}` placeholder. |

The placeholder `{prompt_file}` is replaced at runtime with a temporary `.md` file containing the rendered prompt and
merged context.

---

## `repositories`

Named working directories that executions route into.

```yaml
repositories:
  my-repo:
    path: ./relative/path       # resolved relative to config file
  remote-repo:
    url: https://github.com/org/repo.git
    ref: main                   # optional, only with url
```

Each repository must use **either** `path` or `url`, not both.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | One of path/url | Local filesystem path. `~` is expanded. Relative paths resolve from the config file directory. |
| `url` | string | One of path/url | Git URL for cloning. |
| `ref` | string | No | Git reference (branch, tag, commit). Only valid with `url`. |

**Naming:** Repository names must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`.

At least one repository is required.

---

## `context_sources`

Named shell commands whose stdout is captured and stored as context under a reserved `:key`.

```yaml
context_sources:
  change-summary:
    command: 'printf "summary: %s" "$(cat .propagate-context/:signal.branch)"'
  commit-msg:
    command: 'echo "feat: update docs"'
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | Yes | Shell command to execute. Runs in the execution's working directory. Stdout is stored under `:source-name`. |

**Naming:** Source names must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`.

When invoked via a hook (`:change-summary`), the command runs and its output is stored in the context store at the key
`:change-summary`.

This section is optional. If omitted, no context sources are available.

---

## `signals`

Typed event definitions with payload schemas. Signals activate executions and gate propagation triggers.

```yaml
signals:
  include:                        # optional, load signals from external files
    - ./includes/github-signals.yaml
  repo-change:
    payload:
      branch:
        type: string
        required: true
      files:
        type: list
      urgent:
        type: boolean
    check: "git branch --list {branch} | grep -q ."   # optional validation command
```

### Signal-level fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `payload` | mapping | Yes | Non-empty mapping of field definitions. |
| `check` | string | No | Shell command to validate the signal. Runs after payload validation. |

### Payload field definition

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | string | No | `"string"` | One of: `string`, `number`, `boolean`, `list`, `mapping`, `any`. |
| `required` | boolean | No | `false` | Whether the field must be present in the signal payload. |

**Supported types:**

| Type | Accepts |
|------|---------|
| `string` | Text values |
| `number` | Integers and floats (not booleans) |
| `boolean` | `true` or `false` |
| `list` | YAML/JSON sequences |
| `mapping` | YAML/JSON objects |
| `any` | Any value |

**Naming:** Signal names and payload field names must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`.

### Signal includes

The `include` key loads signal definitions from external YAML files. It accepts a single path or a list of paths,
resolved relative to the config file directory.

```yaml
signals:
  include:
    - ./includes/github-signals.yaml
    - ./includes/custom-signals.yaml
```

Each included file must be a YAML mapping of signal definitions. Duplicate signal names across files or between includes
and inline definitions cause a validation error.

### Signal files

Signals can be provided at runtime via `--signal-file`:

```yaml
# signal-file.yaml
type: repo-change
payload:
  branch: main
  files: [README.md]
```

This section is optional. If omitted, no signals are available.

---

## `executions`

Named units of work. Each execution targets a repository and contains sequential sub-tasks.

```yaml
executions:
  triage-change:
    repository: workspace
    signals:
      - repo-change
    depends_on:
      - some-other-execution
    before:
      - :change-summary
    after:
      - :announcement-note
    on_failure:
      - 'echo "execution failed"'
    sub_tasks:
      - id: triage
        prompt: ./prompts/triage.md
        when: ":ready"
        before:
          - :change-summary
        after:
          - :announcement-note
        on_failure:
          - 'echo "task failed"'
    git:
      branch: { ... }
      commit: { ... }
      push: { ... }
      pr: { ... }
```

### Execution-level fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `repository` | string | Yes | — | Must reference a name defined in `repositories`. |
| `depends_on` | list of strings | No | `[]` | Execution names that must complete before this one runs. Cannot self-reference. No duplicates. |
| `signals` | list | No | `[]` | Signals this execution accepts. See [Execution signals](#execution-signals). |
| `sub_tasks` | list | Yes | — | Non-empty list of sub-task definitions. |
| `git` | mapping | No | `null` | Git automation config. See [git](#git). |
| `before` | list of strings | No | `[]` | Execution-level hook actions run before any sub-tasks. |
| `after` | list of strings | No | `[]` | Execution-level hook actions run after all sub-tasks complete. |
| `on_failure` | list of strings | No | `[]` | Hook actions run if the execution fails. |

### Execution signals

Each entry can be a plain string (signal name) or a mapping with filtering:

```yaml
signals:
  # Simple form — accept any payload
  - repo-change

  # Filtered form — only match when payload fields have specific values
  - signal: repo-change
    when:
      urgent: true
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `signal` | string | Yes | Signal name. Must reference a defined signal. |
| `when` | mapping | No | Payload field-value pairs to match. Field names must exist in the signal's payload definition. |

### Sub-tasks

Sub-tasks run sequentially within an execution.

```yaml
sub_tasks:
  - id: triage
    prompt: ./prompts/triage.md
    when: ":ready"
    before:
      - :change-summary
    after:
      - :announcement-note
    on_failure:
      - 'echo "failed"'
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | Yes | — | Unique identifier within the execution. |
| `prompt` | string | No | `null` | Path to a prompt file. Relative paths resolve from the config file directory. If omitted, no agent is invoked but hooks still run. |
| `when` | string | No | `null` | Conditional execution. `:key` runs if context key exists and is non-empty. `!:key` runs if the key does not exist or is empty. |
| `before` | list of strings | No | `[]` | Hook actions run before the agent. |
| `after` | list of strings | No | `[]` | Hook actions run after the agent succeeds. |
| `on_failure` | list of strings | No | `[]` | Hook actions run if the task fails. |
| `wait_for_signal` | string | No | `null` | Signal name to wait for. Requires `routes`. Must not have `prompt`, `before`, or `after`. |
| `routes` | list | No | `[]` | Route definitions for signal-gated sub-tasks. Requires `wait_for_signal`. |

Task IDs must be unique within an execution.

#### Signal-gated sub-tasks (`wait_for_signal` + `routes`)

A sub-task with `wait_for_signal` blocks until a matching signal arrives, then routes based on the payload. This enables review loops within a single execution.

```yaml
- id: wait-for-verdict
  wait_for_signal: pull_request.labeled
  routes:
    - when: { label: "changes_required" }
      goto: code                          # jump back to sub-task "code"
    - when: { label: "approved" }
      continue: true                      # proceed to next sub-task
```

Each route has:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `when` | mapping | Yes | Payload field-value pairs to match against the received signal. |
| `goto` | string | No | Sub-task ID to jump to (must be defined earlier in the list). Mutually exclusive with `continue`. |
| `continue` | boolean | No | If `true`, proceed to the next sub-task. Mutually exclusive with `goto`. |

Each route must have exactly one of `goto` or `continue`.

When `goto` fires, all sub-tasks from the target onward are re-run (their completed state is cleared). This creates a loop back through those sub-tasks until a `continue` route matches.

Signal-gated sub-tasks require `propagate serve` (they need a ZMQ socket to receive signals).

When `prompt` is set, the prompt file is read, merged context (global + execution + task) is appended as a
`## Context` section, and the result is written to a temporary file passed to the agent command.

---

## `git`

Git automation for an execution. Configured as a nested block inside an execution.

```yaml
git:
  branch:
    name: propagate/my-feature
    base: main
    reuse: true
  commit:
    message_source: commit-msg        # OR message_key: :commit-message
  push:
    remote: origin
  pr:
    base: main
    draft: false
    title_key: :pr-title
    body_key: :pr-body
```

### `git.branch`

Controls branch creation and checkout before sub-tasks run.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | No | `propagate/{execution_name}` | Branch name. Mutually exclusive with `name_key`. |
| `name_key` | string | No | — | Context key (must start with `:`) whose value becomes the branch name. Mutually exclusive with `name`. |
| `base` | string | No | Current branch | Base ref to branch from when creating a new branch. |
| `reuse` | boolean | No | `true` | Reuse an existing branch if it already exists. If `false` and the branch exists, the run fails. |

### `git.commit`

Controls how commits are created after sub-tasks produce file changes.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message_source` | string | One of | Name of a context source whose command output becomes the commit message. |
| `message_key` | string | One of | Context key (must start with `:`) whose value becomes the commit message. |

Exactly **one** of `message_source` or `message_key` must be set.

### `git.push`

Pushes the branch to a remote. Optional.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `remote` | string | Yes | Git remote name (e.g. `origin`). |

If the push is rejected, Propagate fetches, rebases, and retries. If the rebase has conflicts, the run fails.

### `git.pr`

Creates a pull request. Optional. **Requires `push` to be configured.**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `base` | string | No | `git.branch.base` or starting branch | Target branch for the PR. |
| `draft` | boolean | No | `false` | Create the PR as a draft. |
| `title_key` | string | No | First line of commit message | Context key (must start with `:`) for the PR title. |
| `body_key` | string | No | Remaining commit message lines | Context key (must start with `:`) for the PR body. |
| `number_key` | string | No | — | Context key (must start with `:`) where the PR number is stored after creation. |

PRs are created via `gh pr create`.

---

## `propagation`

Defines DAG edges that activate executions after other executions complete.

```yaml
propagation:
  triggers:
    - after: triage-change
      run: update-docs
      on_signal: repo-change          # optional
      when:                           # optional, requires on_signal
        urgent: true
```

### Trigger fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `after` | string | Yes | Execution that must complete to fire this trigger. Must reference a defined execution. |
| `run` | string | Yes | Execution to activate. Must reference a defined execution. |
| `on_signal` | string | No | Only fire if this signal type was received. Must reference a defined signal. |
| `when` | mapping | No | Payload field-value filter. Requires `on_signal`. Field names must exist in the signal's payload. |

The combined graph of `depends_on` edges and propagation triggers must be acyclic.

This section is optional.

---

## Hook Actions

Hook actions appear in `before`, `after`, and `on_failure` lists at both the execution and sub-task level.

### Context source reference

Prefix with `:` to invoke a context source.

```yaml
before:
  - :change-summary     # runs context_sources.change-summary, stores output at :change-summary
```

### Shell command

Any string that is not a context source reference or git command runs as a shell command in the execution's working
directory.

```yaml
after:
  - 'mkdir -p .propagate-context && echo "done" > .propagate-context/status'
```

### Git commands

Prefix with `git:` for git operations. These require a `git` block on the execution.

| Command | Arguments | Description |
|---------|-----------|-------------|
| `git:branch` | — | Create or checkout the configured branch. |
| `git:commit` | — | Stage all changes and commit. |
| `git:push` | — | Push to the configured remote. |
| `git:pr` | — | Create a pull request. |
| `git:pr-labels-add` | `label1 label2 ...` | Add labels to the PR. |
| `git:pr-labels-remove` | `label1 label2 ...` | Remove labels from the PR. |
| `git:pr-labels-list` | `:store_key` | List PR labels and store as JSON in the context key. |
| `git:pr-comment-add` | `:body_key` | Add a PR comment. Body is read from the context key. |
| `git:pr-comments-list` | `:store_key` | List PR comments and store as JSON in the context key. |
| `git:pr-checks-wait` | `:result_key :status_key [interval] [timeout]` | Poll PR checks until all complete. `interval` (seconds, default 10) and `timeout` (seconds, default 1800) are optional positive integers. |

```yaml
after:
  - git:branch
  - git:commit
  - git:push
  - git:pr
  - git:pr-labels-add review-needed documentation
  - git:pr-checks-wait :checks-result :checks-status 30 3600
```

---

## Environment Variables

### User-configurable

| Variable | Default | Description |
|----------|---------|-------------|
| `PROPAGATE_CONTEXT_ROOT` | `.propagate-context` (relative to working directory) | Root directory for the context store. |

### Set at runtime

These are set by Propagate when running hooks and agent commands:

| Variable | Description |
|----------|-------------|
| `PROPAGATE_EXECUTION` | Current execution name. |
| `PROPAGATE_TASK` | Current sub-task ID. Empty string during execution-level hooks. |

---

## Context Store

The context store is a 3-tier key-value store backed by the filesystem.

```
{PROPAGATE_CONTEXT_ROOT}/
├── {key}                           # Global scope
├── {execution_name}/
│   ├── {key}                       # Execution scope
│   └── {task_id}/
│       └── {key}                   # Task scope
```

When a prompt is rendered, context is merged bottom-up: task keys override execution keys, which override global keys.
The merged context is appended to the prompt as:

```markdown
## Context

### key1
value1

### key2
value2
```

**Key pattern:** `^:?[A-Za-z0-9][A-Za-z0-9._-]*$`

Signal payloads are written to context under the `:signal` namespace (e.g. `:signal.branch`, `:signal.files`).

---

## Validation Rules

### Naming patterns

| Entity | Pattern |
|--------|---------|
| Repository names | `^[A-Za-z0-9][A-Za-z0-9._-]*$` |
| Context source names | `^[A-Za-z0-9][A-Za-z0-9._-]*$` |
| Signal names | `^[A-Za-z0-9][A-Za-z0-9._-]*$` |
| Signal field names | `^[A-Za-z0-9][A-Za-z0-9._-]*$` |
| Context keys | `^:?[A-Za-z0-9][A-Za-z0-9._-]*$` |

### Cross-field constraints

- `git.pr` requires `git.push` to be configured.
- `git.commit` requires exactly one of `message_source` or `message_key`.
- `git.branch.name` and `git.branch.name_key` are mutually exclusive.
- `git.branch.name_key`, `git.commit.message_key`, `git.pr.title_key`, `git.pr.body_key`, and `git.pr.number_key` must start with `:`.
- `git.commit.message_source` must reference a defined context source.
- `wait_for_signal` and `routes` must both be present together on a sub-task.
- Sub-tasks with `wait_for_signal` must not have `prompt`, `before`, or `after`.
- Route `goto` targets must reference a sub-task ID defined earlier in the same execution.
- Propagation `when` requires `on_signal` to be set.
- `when` field names must exist in the referenced signal's payload definition.
- `depends_on` entries must reference defined executions and cannot self-reference.
- Repository `ref` is only valid with `url`, not `path`.

### DAG validation

The execution graph (formed by `depends_on` and propagation triggers) must be acyclic. Cycles are detected at config
load time and cause a validation error with the cycle path.

---

## State and Resumption

Run state is persisted to `.propagate-state-{name}.yaml` in the config file directory. Use `--resume` to continue an
interrupted run. Completed phases and tasks are skipped on resume.

---

## CLI Reference

```bash
# Run an execution
propagate run --config config.yaml [--execution name] [--signal name] [--signal-payload '{...}'] [--signal-file path] [--resume]

# Send a signal to a running server
propagate send-signal --config config.yaml --signal name [--signal-payload '{...}']
propagate send-signal --config config.yaml --signal-file path

# Manage context
propagate context set <key> <value> [--global | --local]
propagate context get <key> [--global | --local | --task]
propagate context dump

# Run as a long-lived server
propagate serve --config config.yaml

# Clear all context and run state
propagate clear --config config.yaml
```

### `run` options

| Flag | Description |
|------|-------------|
| `--config` | Path to YAML config file. Required. |
| `--execution` | Execution name to run. Auto-selected if a signal uniquely matches one execution. |
| `--signal` | Signal name to activate. |
| `--signal-payload` | YAML/JSON mapping of signal payload values. Requires `--signal`. |
| `--signal-file` | Path to a YAML/JSON file with `type` and `payload` keys. Mutually exclusive with `--signal`. |
| `--resume` | Resume a previously interrupted run from the state file. |

### `send-signal` options

| Flag | Description |
|------|-------------|
| `--config` | Path to YAML config file. Required. |
| `--signal` | Signal type name. Mutually exclusive with `--signal-file`. |
| `--signal-payload` | YAML/JSON payload mapping. Requires `--signal`. |
| `--signal-file` | Path to a signal file. Mutually exclusive with `--signal`. |

### `clear` options

| Flag | Description |
|------|-------------|
| `--config` | Path to YAML config file. Required. |
| `-f`, `--force` | Also delete cloned repositories recorded in the run state file. Only directories whose name starts with `propagate-repo-` are removed. |

Removes the `.propagate-context/` directory and the `.propagate-state-{name}.yaml` file associated with the config. With `-f`, also removes cloned repository directories that were created during the run.

### `serve` options

| Flag | Description |
|------|-------------|
| `--config` | Path to YAML config file. Required. |

The server binds a ZMQ PULL socket at `ipc:///tmp/propagate-{hash}.sock`, processes signals sequentially, and handles
`SIGTERM`/`SIGINT` for graceful shutdown. It auto-resumes from a state file on startup if one exists.

---

## Complete Example

```yaml
version: "6"

agent:
  command: "claude -p {prompt_file}"

repositories:
  workspace:
    path: ./repos/workspace
  core-api:
    path: ./repos/core-api
  docs-site:
    path: ./repos/docs-site

context_sources:
  change-summary:
    command: 'cat .propagate-context/:signal.branch'
  commit-msg:
    command: 'echo "docs: update generated content"'

signals:
  include:
    - ./includes/github-signals.yaml
  repo-change:
    payload:
      branch:
        type: string
        required: true
      files:
        type: list
        required: true
      urgent:
        type: boolean
    check: "git branch --list {branch} | grep -q ."

executions:
  triage-change:
    repository: workspace
    signals:
      - repo-change
    sub_tasks:
      - id: triage
        prompt: ./prompts/triage.md
        before:
          - :change-summary
        on_failure:
          - 'echo "triage failed" > .propagate-context/failure'

  update-docs:
    repository: docs-site
    depends_on:
      - triage-change
    sub_tasks:
      - id: write-docs
        prompt: ./prompts/update-docs.md
        when: ":ready"

  publish-docs:
    repository: docs-site
    depends_on:
      - update-docs
    git:
      branch:
        name: propagate/publish-docs
        base: main
        reuse: true
      commit:
        message_source: commit-msg
      push:
        remote: origin
      pr:
        base: main
        draft: true
    sub_tasks:
      - id: publish
        prompt: ./prompts/publish.md

propagation:
  triggers:
    - after: triage-change
      run: update-docs
      on_signal: repo-change
    - after: update-docs
      run: publish-docs
```
