# Propagate Configuration Reference

## Overview

Propagate orchestrates chained, cross-repository agent executions. A merged PR in one repo can trigger SDK updates across three languages, which fan-in to trigger docs and integration tests — all wired through a single configuration.

This document defines the configuration format and includes a complete worked example based on a multi-SDK project.

---

## Configuration Structure

A Propagate config is composed of these top-level sections:

| Section | Purpose |
|---------|---------|
| `version` | Config schema version |
| `includes` | Split config across multiple files |
| `agent` | Shell command that runs the LLM agent |
| `defaults` | Default execution settings |
| `repositories` | Git repositories involved in the pipeline |
| `context_sources` | Shell commands that generate runtime context |
| `executions` | Task definitions (what to do) |
| `propagation` | DAG wiring (when to do it) |

---

## Includes

Configs can be split across files. Files are deep-merged in order — later values win on conflicts.

```yaml
includes:
  - ./defaults.yaml
  - ./repositories.yaml
  - ./context-sources.yaml
  - ./executions/sdk-python.yaml
  - ./executions/sdk-typescript.yaml
  - ./executions/sdk-java.yaml
  - ./executions/docs-site.yaml
  - ./executions/integration-tests.yaml
  - ./propagation.yaml

  # Glob patterns: pick up all files in a directory
  # - ./executions/*.yaml

  # Optional includes: no error if file doesn't exist
  # - path: ./overrides/local.yaml
  #   optional: true
```

### Merge behaviour

- Top-level maps are deep-merged. `executions` from `sdk-python.yaml` and `sdk-typescript.yaml` combine into one map.
- Lists are replaced, not appended.
- Explicit file order gives you control; globs use alphabetical order.
- Optional includes allow local overrides or environment-specific patches.

### Recommended directory structure

```
.propagate/
├── propagate.yaml            # root config (includes only)
├── defaults.yaml
├── repositories.yaml
├── context-sources.yaml
├── propagation.yaml
├── executions/
│   ├── sdk-python.yaml
│   ├── sdk-typescript.yaml
│   ├── sdk-java.yaml
│   ├── docs-site.yaml
│   └── integration-tests.yaml
├── guidelines/
│   ├── global.md
│   ├── sdk-general.md
│   ├── python-style.md
│   ├── typescript-style.md
│   ├── java-style.md
│   ├── docs-style.md
│   └── integration-tests.md
├── prompts/
│   ├── python/
│   ├── typescript/
│   ├── java/
│   ├── docs/
│   └── integration/
└── scripts/
```

---

## Agent

Propagate is LLM-agnostic. The agent is a shell command:

```yaml
agent:
  command: aider --message-file {prompt_file}
```

Propagate writes the assembled prompt (prompt file contents + context values) to a temporary file, replaces `{prompt_file}` in the command with the path, and runs it as a subprocess. The agent command inherits the working directory and is responsible for reading the prompt and modifying files. Propagate doesn't know or care what LLM the command uses.

---

## Defaults

Global defaults applied to all executions unless overridden.

```yaml
defaults:
  execution:
    sub_tasks:
      - implementation
      - documentation
      - review
    max_retries: 2
    timeout: 30m
    guidelines:
      - ./guidelines/global.md

  git:
    branch:
      prefix: propagate/
    commit:
      message_source: commit-message   # references a context_source
    pr:
      labels: ["propagate"]
```

Executions inherit these defaults unless they override them.

---

## Repositories

Declare every repository involved in the pipeline.

```yaml
repositories:
  core-api:
    url: git@github.com:pdfdancer/core-api.git
    default_branch: main

  sdk-python:
    url: git@github.com:pdfdancer/sdk-python.git
    default_branch: main

  sdk-typescript:
    url: git@github.com:pdfdancer/sdk-typescript.git
    default_branch: main

  sdk-java:
    url: git@github.com:pdfdancer/sdk-java.git
    default_branch: main

  docs-site:
    url: git@github.com:pdfdancer/docs-site.git
    default_branch: main

  integration-tests:
    url: git@github.com:pdfdancer/integration-tests.git
    default_branch: main
```

Repository keys are used as identifiers throughout the rest of the config.

---

## Context Sources

Shell commands that generate context at runtime. Context sources are defined here and loaded into the context bag by hooks using the `:name` shorthand:

```bash
# In a hook — runs the "openapi-spec" context source and stores the output under that key
propagate context set :openapi-spec
```

```yaml
context_sources:
  openapi-spec:
    command: cat api/openapi.yaml
    working_dir: core-api
    description: "Current OpenAPI spec from core-api"

  changelog-entry:
    command: ./scripts/generate-changelog-entry.sh
    working_dir: core-api

  commit-message:
    command: ./scripts/generate-commit-msg.sh
    description: "Standardised commit message for SDK PRs"

  breaking-changes:
    command: ./scripts/detect-breaking-changes.sh --format=markdown
    working_dir: core-api

  python-sdk-version:
    command: >
      python -c "import tomllib;
      print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
    working_dir: sdk-python
```

---

## Context

Everything an execution knows lives in its context bag — a key-value store. There is one unified mechanism for reading and writing context, with three scopes:

| Scope | CLI flag | Description |
|-------|----------|-------------|
| Local | *(default)* | Current execution's own context |
| Task | `--task name` | A specific upstream execution's context |
| Global | `--global` | Shared across the entire propagation run |

### Auto-populated fields

When an execution starts, its local context is pre-populated from the trigger signal:

| Key | Description |
|-----|-------------|
| `pr_number` | PR number of the triggering PR |
| `pr_title` | PR title |
| `pr_description` | PR body text |
| `pr_branch` | Branch name |
| `pr_labels` | Labels on the PR |
| `diff_summary` | Summary of changes |

Which fields are available depends on the signal type. A `pr_label_changed` signal populates all PR fields. A `manual` trigger may only have what was explicitly passed.

### CLI

```bash
# Write — local (default)
propagate context set changelog docs/CHANGELOG.md

# Write — load from a context source
propagate context set :openapi-spec

# Write — global
propagate context set --global release_version 1.2.0

# Read — local
propagate context get pr_number

# Read — from a specific upstream task
propagate context get changelog --task sdk-python

# Read — global
propagate context get release_version --global
```

### What the agent sees

The agent receives all **global** and **local** context values as input automatically. There is no config needed to wire this — if it's in the bag, the agent sees it.

Upstream task context is **not** visible to the agent by default. To make a value from another task available, pull it into local context in a `before` hook:

```bash
# In a before hook — pulls the upstream value into local context, making it visible to the agent
propagate context set python_changelog "$(propagate context get changelog --task sdk-python)"
```

This gives explicit control over what crosses execution boundaries. The agent only sees what you deliberately pull in.

Context values are also available in hooks and context source commands as environment variables (e.g. `${pr_number}`, `${python_changelog}`).

---

## Executions

Executions are pure task definitions — what to do, not when. Each execution operates on a single repository and consists of configurable sub-tasks.

### Sub-task flow

Sub-tasks run in sequence. Each sub-task either **succeeds** (agent completes and all hooks exit zero) or **fails** (a hook returns non-zero or the agent can't complete). On success, the next sub-task runs. On failure, the execution stops.

`max_retries` on a sub-task handles transient failures — the sub-task is retried up to that many times before it's considered failed.

The default sub-task chain is:

```
implementation → documentation → review
```

Executions can override the default sub-tasks. For example, integration tests only need `implementation`.

### Gating with `wait_for`

By default, sub-tasks advance automatically on success. A sub-task can declare `wait_for` with a signal to pause the execution until that signal fires. This uses the same signal types and filters as the propagation block — no new concepts:

```yaml
sub_tasks:
  - id: design
    prompt: ./prompts/design.md
    hooks:
      after: |
        gh pr edit --add-label design_complete

  - id: implementation
    wait_for:
      type: pr_label_changed
      filters:
        labels: ["design_approved"]
    prompt: ./prompts/implement.md
```

In this example, after the design sub-task succeeds, the execution pauses at `implementation`. It resumes when `design_approved` appears on the PR — which happens when a human reviews the design and adds the label.

This keeps human checkpoints inside the execution where they belong, while reusing the signal vocabulary that already exists.

### Hooks

Every sub-task supports `before`, `after`, and `on_failure` hooks — arbitrary shell commands that run around the agent task:

```yaml
hooks:
  before: |
    gh pr edit --remove-label change_required
    pip install -e ".[dev]"
  after: |
    pytest tests/unit -x --tb=short
    gh pr edit --add-label implementation_done
  on_failure: |
    gh pr edit --add-label failed
```

`before` runs before the agent starts. `after` runs after the agent completes successfully and is also where validation happens (tests, linting). `on_failure` runs when the sub-task fails — either because a hook returned non-zero or the agent couldn't complete.

Since hooks are plain shell commands, label management is just `gh pr edit` calls — no special abstraction needed. This also means hooks can do anything else: send notifications, update dashboards, trigger external systems.

### Git workflow

Each execution operates on a PR. The core rule is simple: if the execution already has a PR (because one triggered it), it works on that PR's branch. If it doesn't (downstream execution or manual trigger without PR context), it creates a new branch and opens a PR after the first push.

#### Branch

For executions that need to create a branch, the name is derived from the originating PR's title, slugified, with a configurable prefix:

```yaml
git:
  branch:
    prefix: propagate/   # "Add user search" → propagate/add-user-search
```

For executions working on an existing PR, the branch config is ignored — Propagate checks out the PR's branch directly.

#### Commit and push

After every sub-task completes, Propagate commits and pushes. This is not configurable — it's how the system works. Every sub-task boundary is a commit.

The commit message is generated by a shell command, referenced as a context source:

```yaml
git:
  commit:
    message_source: commit-message   # references a context_source

context_sources:
  commit-message:
    command: ./scripts/generate-commit-msg.sh
```

This gives full control over commit messages — the script can inspect the diff, read the sub-task id from the environment, or apply any convention.

#### PR creation

For downstream executions (no existing PR), a PR is opened automatically after the first commit+push. The PR inherits the labels configured in `defaults.git.pr.labels`.

### Context in practice

Context sources, auto-populated fields, and hook-set values all live in the same bag. A typical execution loads what it needs in `before` hooks and writes outputs in `after` hooks:

```yaml
sub_tasks:
  - id: implementation
    prompt: ./prompts/python/implement.md
    hooks:
      before: |
        propagate context set :openapi-spec
        propagate context set :breaking-changes
        pip install -e ".[dev]"
      after: |
        pytest tests/unit -x --tb=short
  - id: review
    prompt: ./prompts/python/review.md
    hooks:
      after: |
        propagate context set package_url "$(pip show sdk | grep Version | cut -d' ' -f2)"
        gh pr edit --add-label ready_for_review
```

The context is shared across all sub-tasks within an execution. An earlier sub-task's hook can set a value, and a later sub-task's hook or prompt can read it.

When the execution completes, its context becomes available to downstream executions. A downstream hook can pull values into its own local context:

```bash
# In a downstream execution's before hook
propagate context set python_pkg "$(propagate context get package_url --task sdk-python)"
```

There is no separate `result` block. The context *is* the result.

### Full execution example

```yaml
executions:
  update-sdk-python:
    repository: sdk-python
    guidelines:
      - ./guidelines/sdk-general.md
      - ./guidelines/python-style.md

    sub_tasks:
      - id: implementation
        prompt: ./prompts/python/implement.md
        hooks:
          before: |
            propagate context set :openapi-spec
            propagate context set :changelog-entry
            propagate context set :breaking-changes
            propagate context set :python-sdk-version
            gh pr edit --remove-label change_required
            pip install -e ".[dev]"
          after: |
            pytest tests/unit -x --tb=short
          on_failure: |
            gh pr edit --add-label failed

      - id: documentation
        prompt: ./prompts/python/document.md
        hooks:
          before: pip install sphinx
          after: |
            cd docs && make html 2>&1 | tee /tmp/sphinx-output.log
            propagate context set changelog docs/CHANGELOG.md

      - id: review
        prompt: ./prompts/python/review.md
        hooks:
          before: ./scripts/wait-for-github-build.sh
          after: |
            propagate context set package_url "$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
            gh pr edit --add-label ready_for_review
          on_failure: |
            gh pr edit --add-label change_required
```

---

## Propagation

The propagation block is the single place that wires the DAG — what triggers what. This replaces the need for separate signal definitions and `triggered_by` fields on executions.

Each entry combines a signal (the trigger condition) with the actions to take.

### Signal types

| Type | Description |
|------|-------------|
| `pr_closed_merged` | A PR was merged on a specific repo/branch |
| `pr_label_changed` | A PR label was added or removed |
| `pr_created` | A new PR was opened |
| `manual` | Human-initiated trigger |
| `tasks_completed` | One or more upstream tasks finished successfully |
| `task_failed` | An upstream task reported a problem |

### Fan-out and fan-in

Fan-out (one trigger, multiple tasks) and fan-in (multiple tasks must complete before proceeding) are expressed directly:

```yaml
propagation:
  # Fan-out: one merged PR triggers three parallel SDK updates
  - signal:
      type: pr_closed_merged
      repository: core-api
      filters:
        base_branch: main
        labels: ["release"]
    execute: [update-sdk-python, update-sdk-typescript, update-sdk-java]
    mode: parallel

  # Manual trigger wired to the same tasks
  - signal:
      type: manual
      description: "Force-sync all SDKs to latest API spec"
    execute: [update-sdk-python, update-sdk-typescript, update-sdk-java]
    mode: parallel

  # Fan-in: all three SDKs must complete before docs and tests start
  - signal:
      type: tasks_completed
      tasks: [update-sdk-python, update-sdk-typescript, update-sdk-java]
    execute: [update-docs-site, run-integration-tests]
    mode: parallel

  # Failure notification
  - signal:
      type: task_failed
      task: run-integration-tests
    notify:
      - channel: slack
        webhook_env: SLACK_WEBHOOK_CI
        template: "Integration tests failed. Details: {{execution.url}}"
```

### N-to-N relationships

The propagation block supports arbitrary graph topologies:

```yaml
# on DONE repo-a → do repo-b and repo-c
- signal:
    type: tasks_completed
    tasks: [task-a]
  execute: [task-b, task-c]

# on DONE repo-b AND repo-c → do repo-d
- signal:
    type: tasks_completed
    tasks: [task-b, task-c]
  execute: [task-d]
```

---

## Complete Example

Below is the full config for a project with a core API, three SDK clients (Python, TypeScript, Java), a docs site, and an integration test suite.

### `propagate.yaml`

```yaml
version: "1"

includes:
  - ./defaults.yaml
  - ./repositories.yaml
  - ./context-sources.yaml
  - ./executions/sdk-python.yaml
  - ./executions/sdk-typescript.yaml
  - ./executions/sdk-java.yaml
  - ./executions/docs-site.yaml
  - ./executions/integration-tests.yaml
  - ./propagation.yaml
```

### `defaults.yaml`

```yaml
defaults:
  execution:
    sub_tasks:
      - implementation
      - documentation
      - review
    max_retries: 2
    timeout: 30m
    guidelines:
      - ./guidelines/global.md

  git:
    branch:
      prefix: propagate/
    commit:
      message_source: commit-message
    pr:
      labels: ["propagate"]
```

### `repositories.yaml`

```yaml
repositories:
  core-api:
    url: git@github.com:pdfdancer/core-api.git
    default_branch: main

  sdk-python:
    url: git@github.com:pdfdancer/sdk-python.git
    default_branch: main

  sdk-typescript:
    url: git@github.com:pdfdancer/sdk-typescript.git
    default_branch: main

  sdk-java:
    url: git@github.com:pdfdancer/sdk-java.git
    default_branch: main

  docs-site:
    url: git@github.com:pdfdancer/docs-site.git
    default_branch: main

  integration-tests:
    url: git@github.com:pdfdancer/integration-tests.git
    default_branch: main
```

### `context-sources.yaml`

```yaml
context_sources:
  openapi-spec:
    command: cat api/openapi.yaml
    working_dir: core-api
    description: "Current OpenAPI spec from core-api"

  changelog-entry:
    command: ./scripts/generate-changelog-entry.sh
    working_dir: core-api

  commit-message:
    command: ./scripts/generate-commit-msg.sh
    description: "Standardised commit message for SDK PRs"

  breaking-changes:
    command: ./scripts/detect-breaking-changes.sh --format=markdown
    working_dir: core-api

  python-sdk-version:
    command: >
      python -c "import tomllib;
      print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
    working_dir: sdk-python
```

### `executions/sdk-python.yaml`

```yaml
executions:
  update-sdk-python:
    repository: sdk-python
    guidelines:
      - ./guidelines/sdk-general.md
      - ./guidelines/python-style.md

    sub_tasks:
      - id: implementation
        prompt: ./prompts/python/implement.md
        hooks:
          before: |
            propagate context set :openapi-spec
            propagate context set :changelog-entry
            propagate context set :breaking-changes
            propagate context set :python-sdk-version
            gh pr edit --remove-label change_required
            pip install -e ".[dev]"
          after: |
            pytest tests/unit -x --tb=short
          on_failure: |
            gh pr edit --add-label failed

      - id: documentation
        prompt: ./prompts/python/document.md
        hooks:
          before: pip install sphinx
          after: |
            cd docs && make html 2>&1 | tee /tmp/sphinx-output.log
            propagate context set changelog docs/CHANGELOG.md

      - id: review
        prompt: ./prompts/python/review.md
        hooks:
          before: ./scripts/wait-for-github-build.sh
          after: |
            propagate context set package_url "$(pip show pdfdancer-sdk | grep Version | cut -d' ' -f2)"
            gh pr edit --add-label ready_for_review
          on_failure: |
            gh pr edit --add-label change_required
```

### `executions/sdk-typescript.yaml`

```yaml
executions:
  update-sdk-typescript:
    repository: sdk-typescript
    guidelines:
      - ./guidelines/sdk-general.md
      - ./guidelines/typescript-style.md

    sub_tasks:
      - id: implementation
        prompt: ./prompts/typescript/implement.md
        hooks:
          before: |
            propagate context set :openapi-spec
            propagate context set :changelog-entry
            propagate context set :breaking-changes
            gh pr edit --remove-label change_required
            npm ci
          after: npm run test:unit
          on_failure: |
            gh pr edit --add-label failed

      - id: documentation
        prompt: ./prompts/typescript/document.md
        hooks:
          after: |
            npm run docs:build
            propagate context set changelog docs/CHANGELOG.md

      - id: review
        prompt: ./prompts/typescript/review.md
        hooks:
          before: ./scripts/wait-for-github-build.sh
          after: |
            propagate context set package_url "$(node -p "require('./package.json').version")"
            gh pr edit --add-label ready_for_review
          on_failure: |
            gh pr edit --add-label change_required
```

### `executions/sdk-java.yaml`

```yaml
executions:
  update-sdk-java:
    repository: sdk-java
    guidelines:
      - ./guidelines/sdk-general.md
      - ./guidelines/java-style.md

    sub_tasks:
      - id: implementation
        prompt: ./prompts/java/implement.md
        hooks:
          before: |
            propagate context set :openapi-spec
            propagate context set :changelog-entry
            propagate context set :breaking-changes
            gh pr edit --remove-label change_required
            mvn dependency:resolve
          after: mvn test -pl core
          on_failure: |
            gh pr edit --add-label failed

      - id: documentation
        prompt: ./prompts/java/document.md
        hooks:
          after: |
            mvn javadoc:javadoc
            propagate context set changelog docs/CHANGELOG.md

      - id: review
        prompt: ./prompts/java/review.md
        hooks:
          before: ./scripts/wait-for-github-build.sh
          after: |
            propagate context set package_url "$(mvn help:evaluate -Dexpression=project.version -q -DforceStdout)"
            gh pr edit --add-label ready_for_review
          on_failure: |
            gh pr edit --add-label change_required
```

### `executions/docs-site.yaml`

```yaml
executions:
  update-docs-site:
    repository: docs-site
    guidelines:
      - ./guidelines/docs-style.md

    sub_tasks:
      - id: implementation
        prompt: ./prompts/docs/update-api-reference.md
        hooks:
          before: |
            propagate context set :openapi-spec
            propagate context set :changelog-entry
            propagate context set python_changelog "$(propagate context get changelog --task sdk-python)"
            propagate context set ts_changelog "$(propagate context get changelog --task sdk-typescript)"
            propagate context set java_changelog "$(propagate context get changelog --task sdk-java)"
            npm ci
          after: npm run build
          on_failure: |
            gh pr edit --add-label failed

      - id: documentation
        prompt: ./prompts/docs/write-changelog-page.md

      - id: review
        prompt: ./prompts/docs/review.md
        hooks:
          before: ./scripts/wait-for-github-build.sh
          after: |
            propagate context set docs_url "$(npm run build:url --silent)"
            gh pr edit --add-label ready_for_review
          on_failure: |
            gh pr edit --add-label change_required
```

### `executions/integration-tests.yaml`

```yaml
executions:
  run-integration-tests:
    repository: integration-tests
    guidelines:
      - ./guidelines/integration-tests.md

    # Override defaults: no documentation or review needed
    sub_tasks:
      - id: implementation
        prompt: ./prompts/integration/run-all.md
        timeout: 60m
        hooks:
          before: |
            propagate context set python_pkg "$(propagate context get package_url --task sdk-python)"
            propagate context set ts_pkg "$(propagate context get package_url --task sdk-typescript)"
            propagate context set java_pkg "$(propagate context get package_url --task sdk-java)"
            docker compose -f docker-compose.test.yml up -d
            ./scripts/wait-for-services.sh
          after: |
            docker compose -f docker-compose.test.yml down
            propagate context set test_report reports/results.json
            gh pr edit --add-label tests_passed
          on_failure: |
            gh pr edit --add-label tests_failed
```

### `propagation.yaml`

```yaml
propagation:
  # Fan-out: merged release PR triggers all SDK updates
  - signal:
      type: pr_closed_merged
      repository: core-api
      filters:
        base_branch: main
        labels: ["release"]
    execute: [update-sdk-python, update-sdk-typescript, update-sdk-java]
    mode: parallel

  # Manual trigger wired to the same tasks
  - signal:
      type: manual
      description: "Force-sync all SDKs to latest API spec"
    execute: [update-sdk-python, update-sdk-typescript, update-sdk-java]
    mode: parallel

  # Fan-in: all three SDKs must complete before docs and tests
  - signal:
      type: tasks_completed
      tasks: [update-sdk-python, update-sdk-typescript, update-sdk-java]
    execute: [update-docs-site, run-integration-tests]
    mode: parallel

  # Failure notification
  - signal:
      type: task_failed
      task: run-integration-tests
    notify:
      - channel: slack
        webhook_env: SLACK_WEBHOOK_CI
        template: "Integration tests failed. Details: {{execution.url}}"
```

---

## Execution Flow Diagram

```
┌─────────────────────┐
│  core-api            │
│  PR merged + release │
└─────────┬───────────┘
          │
          ├──────────────────┬──────────────────┐
          ▼                  ▼                  ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ update-sdk-     │ │ update-sdk-     │ │ update-sdk-     │
│ python          │ │ typescript      │ │ java            │
│                 │ │                 │ │                 │
│ implement       │ │ implement       │ │ implement       │
│ document        │ │ document        │ │ document        │
│ review          │ │ review          │ │ review          │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                   │
         └───────────┬───────┴───────────────────┘
                     │ fan-in (all three)
          ┌──────────┴──────────┐
          ▼                     ▼
┌─────────────────┐   ┌─────────────────────┐
│ update-docs-    │   │ run-integration-    │
│ site            │   │ tests               │
│                 │   │                     │
│ implement       │   │ implement (only)    │
│ document        │   │                     │
│ review          │   │                     │
└─────────────────┘   └─────────────────────┘
```
