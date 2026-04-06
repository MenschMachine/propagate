# Propagate

A task orchestration system that coordinates multi-stage agent workflows across Git repositories. Executions form a DAG, each operating on a repository with sequential sub-tasks driven by agent commands. Supports signals (typed events), propagation triggers, and a 3-tier context store.

## Installation

Requires Python 3.10+.

```bash
python -m venv venv
./venv/bin/pip install -e .

# With webhook support
./venv/bin/pip install -e ".[webhook]"
```

## Quick Start

Define a config file:

```yaml
version: "6"

agent:
  command: 'your-agent-command "{prompt_file}"'

repositories:
  my-app:
    path: ../my-app

executions:
  update:
    repository: my-app
    sub_tasks:
      - id: implement
        prompt: ./prompts/implement.md
```

Run it:

```bash
propagate run --config config.yaml
```

## Core Concepts

### Executions

Named units of work that run in a repository directory. Each execution contains sequential sub-tasks, where each sub-task renders a prompt and invokes the configured agent command.

```yaml
executions:
  build:
    repository: app
    sub_tasks:
      - id: implement
        prompt: ./prompts/implement.md
      - id: review
        prompt: ./prompts/review.md
```

### Signals

Typed events with validated payloads that trigger executions. Declared in config, supplied via CLI or webhook.

```yaml
signals:
  deploy:
    payload:
      branch:
        type: string
        required: true
      dry-run:
        type: boolean
```

```bash
propagate run --config config.yaml \
  --signal deploy \
  --signal-payload '{branch: main, dry-run: false}'
```

Signal data is accessible in hooks and prompt templates via the context store under the `:signal.*` namespace.

### Parameterized Includes

Shared signal and execution bundles can be reused with per-project parameters:

```yaml
executions:
  include:
    - path: ./executions/review-loop.yaml
      with:
        repository: app
        implement_prompt: ./prompts/implement.md
        summarize_prompt: ./prompts/summarize.md
```

Included files can reference those parameters in scalar values using `{{ name }}` placeholders. Relative prompt paths
still resolve from the root config file directory after rendering. Placeholder rendering applies to included file
content only; the root config itself is not templated.

### Propagation Triggers

DAG edges that activate downstream executions after an upstream one completes, optionally gated on a signal:

```yaml
propagation:
  triggers:
    - after: build
      run: deploy
      on_signal: approved
```

Triggers support payload filtering with `when` clauses to match on specific payload field values.

### Context Store

A 3-tier key-value store (global, execution-scoped, task-scoped) persisted to `.propagate-context/`. Context sources are shell commands whose output is stored under reserved `:key` names:

```yaml
context_sources:
  commit-msg:
    command: echo "propagate: update sdk"

executions:
  update:
    repository: app
    sub_tasks:
      - id: implement
        prompt: ./prompts/implement.md
        before:
          - :commit-msg    # runs the context source, stores result
```

### Git Automation

Hook commands for branch management, commits, pushes, and PR creation:

```yaml
executions:
  update-sdk:
    repository: sdk
    git:
      branch:
        name: propagate/update-sdk
        base: main
      commit:
        message_source: commit-msg
      push:
        remote: origin
      pr:
        base: main
    before:
      - git:branch
    sub_tasks:
      - id: implement
        prompt: ./prompts/implement.md
        after:
          - git:commit
    after:
      - git:push
      - git:pr
```

Additional PR commands: `git:pr-checks-wait`, `git:pr-labels-add`, `git:pr-labels-remove`, `git:pr-comment-add`.

### Sub-Task Hooks

Each sub-task supports lifecycle hooks:

- `before` -- runs before the agent prompt
- `after` -- runs after the agent succeeds
- `on_failure` -- runs if the before hook or agent fails

Hooks can be shell commands, context source loads (`:source-name`), or git commands (`git:*`).

Tasks can also abort intentionally from inside prompts or scripts with a structured failure:

```bash
propagate fail unable-to-implement "Blocked by upstream backend bug in PDF metadata parsing"
```

This exits the current run immediately instead of relying on another retry loop to fail later.

### Conditional Execution

Sub-tasks support a `when` field that skips based on context key values:

```yaml
sub_tasks:
  - id: wait-ci
    before:
      - git:pr-checks-wait :check-results :checks-passed
  - id: on-pass
    when: ":checks-passed"
    prompt: ./prompts/on-pass.md
  - id: on-fail
    when: "!:checks-passed"
    prompt: ./prompts/on-fail.md
```

## CLI

```bash
# Run an execution
propagate run --config config.yaml [--execution NAME] [--signal TYPE] [--signal-payload YAML] [--resume]

# Send a signal to a running instance
propagate send-signal --config config.yaml --signal TYPE [--signal-payload YAML]

# Manage context
propagate context get KEY [--global | --local | --task NAME]
propagate context set KEY VALUE [--global | --local]
propagate context dump

# Abort the current task/run with a structured failure kind
propagate fail unable-to-implement "reason"
```

### Resume

Runs persist state to `.propagate-state-{name}.yaml`. If interrupted, resume with:

```bash
propagate run --config config.yaml --resume
```

## Webhook Server

A GitHub webhook listener that maps events to signals and forwards them to a running propagate instance via ZeroMQ.

```bash
propagate-webhook --config config.yaml --port 8080 --secret YOUR_SECRET
```

Supports `pull_request`, `issues`, `push`, `issue_comment`, and other GitHub events. See [docs/WEBHOOK.md](docs/WEBHOOK.md) for setup.

For local development, use `scripts/propagate-setup.py` to create Smee channels and GitHub webhooks. See [docs/WEBHOOK.md](docs/WEBHOOK.md) for details.

## External Signal Delivery

When signal-gated propagation triggers exist, the scheduler opens a ZeroMQ IPC socket and waits for external signals:

```bash
# Terminal 1: run builds, then wait
propagate run --config config.yaml --execution build

# Terminal 2: send approval signal
propagate send-signal --config config.yaml --signal approved
```

## Signal Checks

Propagation triggers can define `check` commands that probe whether a condition is already true, avoiding indefinite waits:

```yaml
signals:
  pull_request.labeled:
    payload:
      repository: { type: string, required: true }
      label: { type: string, required: true }
    check: "gh pr list --repo {repository} --label {label} --state open --json number --jq 'length > 0'"
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PROPAGATE_CONTEXT_ROOT` | Override context store root directory |
| `PROPAGATE_EXECUTION` | Current execution name (set during runs) |
| `PROPAGATE_TASK` | Current task ID (set during runs) |

## Development

```bash
# Run tests
./venv/bin/python -m pytest tests/ -v

# Lint
./venv/bin/ruff check propagate_*/ tests/

# Lint with auto-fix
./venv/bin/ruff check --fix propagate_*/ tests/
```

## Documentation

- [Signals](docs/SIGNALS.md) -- signal system, payload validation, filtering
- [Git Automation](docs/GIT.md) -- branch, commit, push, PR commands
- [Webhook Server](docs/WEBHOOK.md) -- GitHub webhook setup and event mapping
