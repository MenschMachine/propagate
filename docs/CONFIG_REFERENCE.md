# Configuration Reference

Propagate uses a YAML configuration file to define the entire execution DAG. This document covers every available
option.

## Top-Level Structure

```yaml
version: "6"              # Required
agents:                    # Required (map of named agents)
  default:
    command: "claude -p {prompt_file}"
  agent-easy:
    command: "claude -p {prompt_file} --easy"
agent: default            # Names the default agent from the agents map
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
clone_dir: ./clones        # Optional
repo_cache_dir: ./cache    # Optional
```

All keys not listed above are rejected.

---

## `clone_dir`

**Optional.** Directory where remote repositories are cloned into. Relative paths are resolved from the config file directory. Can be overridden by the `PROPAGATE_CLONE_DIR` environment variable.

```yaml
clone_dir: ./clones
```

If not set, clones land in the system temp directory.

---

## `repo_cache_dir`

**Optional.** Directory for persistent bare-repo clone caches. Each remote repository is cloned once as a bare repo under `{repo_cache_dir}/{name}.git` and refreshed (`git fetch`) on subsequent runs. Each execution gets a fresh local clone from the bare repo, which is faster than a full remote clone.

Defaults to `.repo-cache` relative to the config file. Relative paths are resolved from the config file directory. Safe for concurrent runs: a per-repo file lock (`fcntl.LOCK_EX`) serialises bare-repo access.

```yaml
repo_cache_dir: ./cache   # default: .repo-cache
```

---

## `version`

**Required.** Must be the string `"6"`.

```yaml
version: "6"
```

---

## `agents` and `agent`

Defines one or more named agent commands. The `agent` key names the default agent used for all sub-tasks unless a sub-task overrides it via the `:agent` context key.

```yaml
agents:
  default:
    command: "claude -p {prompt_file}"
  agent-easy:
    command: "claude -p {prompt_file} --easy"
  agent-hard:
    command: "claude -p {prompt_file} --hard"
agent: default
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agents` | map | Yes | Map of agent name to command. Each command must contain the `{prompt_file}` placeholder. |
| `agent` | string | Yes | Name of the default agent in the `agents` map. |

**Runtime agent selection:** Sub-tasks can set `:agent <name>` in global context (e.g. via an earlier assess-complexity task). The agent command is resolved at runtime by reading `:agent` from global context and looking it up in the `agents` map. If `:agent` is not set, the default agent is used.

The placeholder `{prompt_file}` is replaced at runtime with a temporary `.md` file containing the rendered prompt and merged context.

**Backwards compatibility:** The legacy format `agent: {command: "..."}` (a single command) is still supported. It is automatically converted to `agents: {default: {command: "..."}}, agent: default`.

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
| `url` | string | One of path/url | Git URL for cloning. SSH URLs (`git@...`) are automatically converted to HTTPS at clone time. |
| `ref` | string | No | Git reference (branch, tag, commit). Only valid with `url`. |

**Naming:** Repository names must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`.

At least one repository is required.

---

## `context_sources`

Named shell commands whose stdout is captured and stored as context under a reserved `:key`.

```yaml
context_sources:
  change-summary:
    command: 'printf "summary: %s" "$(cat .propagate-context-propagate/:signal.branch)"'
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
    - ./signals/github-signals.yaml
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

The `include` key loads signal definitions from external YAML files. It accepts:

- a single path string
- a single mapping with `path` and optional `with`
- a list mixing path strings and `path`/`with` mappings

Include paths are resolved relative to the root config file directory.

```yaml
signals:
  include:
    - ./signals/github-signals.yaml
    - ./signals/custom-signals.yaml
    - path: ./signals/review.yaml
      with:
        repository: myorg/myrepo
        required_label: approved
```

Each included file must be a YAML mapping of signal definitions. Duplicate signal names across include files cause a
validation error. Inline definitions override included ones with the same name.

Included files may reference `with` parameters inside scalar string values using `{{ name }}` placeholders:

```yaml
# ./signals/review.yaml
pull_request.labeled:
  payload:
    repository:
      type: string
      required: true
  check: "gh pr list --repo {{ repository }} --label {{ required_label }} --state open --json number --jq 'length > 0'"
```

Templating rules:

- placeholder rendering is applied only to included file content; root config values are not templated
- placeholders are allowed only in scalar values, not YAML keys
- a value that is exactly `{{ name }}` preserves the parameter type
- placeholders embedded inside a larger string are interpolated as text
- `with` values must be strings, numbers, or booleans
- missing or unused parameters are validation errors

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
    agent: agent-easy        # Optional: override default agent for all sub-tasks in this execution
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

### `agent`

Optional. Specifies which agent to use for all sub-tasks in this execution, overriding the global default and the `:agent` context key.

```yaml
executions:
  implementation:
    repository: examples
    agent: agent-easy  # Use agent-easy for all sub-tasks in this execution
    sub_tasks:
      - id: implement
        prompt: ./prompts/implement.md
```

Agent resolution order: `execution.agent` → `:agent` context key → `agent` (global default).

### Execution includes

The `include` key loads execution definitions from external YAML files. It accepts:

- a single path string
- a single mapping with `path` and optional `with`
- a list mixing path strings and `path`/`with` mappings

Include paths are resolved relative to the root config file directory.

```yaml
executions:
  include:
    - ./executions/deploy.yaml
    - ./executions/build.yaml
    - path: ./executions/review-loop.yaml
      with:
        repository: app
        implement_prompt: ./prompts/implement.md
        summarize_prompt: ./prompts/summarize.md
        retry_label: changes_required
        approve_label: approved
```

Each included file must be a YAML mapping of execution definitions. Duplicate execution names across include files cause
a validation error. Inline definitions override included ones with the same name.

Included files may reference `with` parameters inside scalar string values using `{{ name }}` placeholders:

```yaml
# ./executions/review-loop.yaml
review_loop:
  repository: "{{ repository }}"
  sub_tasks:
    - id: implement
      prompt: "{{ implement_prompt }}"
    - id: summarize
      prompt: "{{ summarize_prompt }}"
    - id: wait-for-verdict
      wait_for_signal: pull_request.labeled
      routes:
        - when: { label: "{{ retry_label }}" }
          goto: implement
        - when: { label: "{{ approve_label }}" }
          continue: true
```

After rendering, relative prompt paths and other path-like values still resolve from the root config file directory, not
from the included file's directory.

Templating in execution includes follows the same rules as signal includes above: rendering applies only to included
file content, not to root config values.

Unlike signal includes, execution includes may also template the top-level execution name itself. This makes it
possible to instantiate the same included workflow multiple times with different execution names:

```yaml
# ./executions/review-loop.yaml
"{{ execution_name }}":
  repository: "{{ repository }}"
  sub_tasks:
    - id: implement
      prompt: "{{ implement_prompt }}"
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
| `when` | mapping | No | Payload field-value pairs to match. Field names must exist in the signal's payload definition. Values can be literals or matcher objects such as `{ equals_context: :key }`. |

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
| `when` | string or mapping | No | `null` | Conditional execution. `:key` runs if an execution-scoped context key exists and is non-empty. `!:key` runs if the key does not exist or is empty. Mapping form can declare an explicit scope. |
| `before` | list of strings | No | `[]` | Hook actions run before the agent. |
| `after` | list of strings | No | `[]` | Hook actions run after the agent succeeds. |
| `on_failure` | list of strings | No | `[]` | Hook actions run if the task fails. |
| `goto` | string | No | `null` | Sub-task ID to jump to after this task completes (must be defined earlier in the list). Mutually exclusive with `wait_for_signal`. |
| `max_goto` | integer | No | `3` | Maximum number of times this sub-task's `goto` can fire before raising an error. Requires `goto`. Prevents infinite retry loops. |
| `on_max_goto` | string | No | `"fail"` | What happens when `max_goto` is exceeded. `"fail"` raises an error (default). `"continue"` logs a warning and proceeds to the next sub-task. Requires `goto`. |
| `wait_for_signal` | string | No | `null` | Signal name to wait for. Requires `routes`. Must not have `prompt` or `on_failure`. |
| `routes` | list | No | `[]` | Route definitions for signal-gated sub-tasks. Requires `wait_for_signal`. |
| `must_set` | list of strings or mappings | No | `[]` | Context keys the agent must set during this task. Validated after the agent phase; raises an error if any key is missing or empty. Keys are injected into the agent prompt as a notice, including the correct scoped `propagate context set` command. Must not be used with `wait_for_signal`. |

Task IDs must be unique within an execution.

Scoped context references use this mapping form:

```yaml
when:
  key: :review-findings
  scope: execution

must_set:
  - key: :implementation-briefs
    scope: global
```

Supported scopes:
- `execution`: current execution context
- `global`: global context root
- `task`: a specific execution or execution/task path, supplied via `task`

Legacy bare string references remain execution-scoped for backward compatibility.

#### Signal-gated sub-tasks (`wait_for_signal` + `routes`)

A sub-task with `wait_for_signal` blocks until a matching signal arrives, then routes based on the payload. This enables review loops within a single execution.

```yaml
- id: wait-for-verdict
  wait_for_signal: pull_request.labeled
  routes:
    - when: { label: "changes_required" }
      goto: code                          # jump back to sub-task "code"
    - when:
        label: "approved"
        pr_number:
          equals_context: :api-docs-pr-number
      continue: true                      # proceed to next sub-task
```

Each route has:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `when` | mapping | Yes | Payload field-value pairs to match against the received signal. Values can be literals or matcher objects such as `{ equals_context: :key }`. |
| `goto` | string | No | Sub-task ID to jump to (must be defined earlier in the list). Mutually exclusive with `continue`. |
| `continue` | boolean | No | If `true`, proceed to the next sub-task. Mutually exclusive with `goto`. |

Each route must have exactly one of `goto` or `continue`.

When `goto` fires, all sub-tasks from the target onward are re-run (their completed state is cleared). This creates a loop back through those sub-tasks until a `continue` route matches.

#### Direct `goto` on sub-tasks

A sub-task can use `goto` directly (without `wait_for_signal`) for automated retry loops. Direct `goto` requires `when` to prevent unconditional infinite loops. Use `max_goto` to limit retries:

```yaml
- id: reroute-on-check-failure
  when: "!:checks-passed"
  goto: implement
  max_goto: 5                                 # default is 3
```

This is a control-flow node — no `prompt` is needed. The `when` condition and hooks do the work; the `goto` handles routing. When `max_goto` is exceeded, the default behavior (`on_max_goto: fail`) raises an error. Set `on_max_goto: continue` to skip the goto and proceed to the next sub-task instead:

```yaml
- id: reroute-on-suggestions
  when: ":review-suggestions"
  goto: implement
  max_goto: 3
  on_max_goto: continue                         # proceed instead of failing
```

Signal-gated sub-tasks require `propagate serve` (they need a ZMQ socket to receive signals).

If a task determines the work is fundamentally blocked and should not loop again, abort explicitly from the prompt or
any invoked script:

```bash
propagate fail unable-to-implement "Blocked by upstream bug or missing prerequisite"
```

That raises a terminal execution error immediately, which is useful for review loops where another retry would be
pointless.

#### "Won't fix" escape hatch

When the implement agent decides review findings are not worth fixing, it can set a `:wontfix` context key to break out
of the review loop gracefully. The key's value should contain the reasoning — it doubles as the PR comment body:

```yaml
- id: implement
  before:
    - git:branch
    - 'propagate context delete :wontfix'       # reset flag each iteration
  prompt: ./prompts/implement.md
  # Agent can run: propagate context set --stdin :wontfix <<'EOF' ...

- id: clear-findings-on-wontfix
  when: ":wontfix"
  after:
    - 'propagate context delete :review-findings'

- id: review
  when: "!:wontfix"
  before:
    - 'propagate context delete :review-findings'
  prompt: ./prompts/review.md

- id: reroute-on-review-findings
  when: ":review-findings"
  goto: implement

# ... later, after git:publish creates the PR ...

- id: post-wontfix-comment
  when: ":wontfix"
  before:
    - git:pr-comment-add :wontfix
```

The `clear-findings-on-wontfix` step is necessary because when a `goto` resets tasks, context keys persist on disk. If
review is skipped (due to `:wontfix`), its `before` hook never runs to delete the stale `:review-findings`, which would
otherwise re-trigger the reroute. The `post-wontfix-comment` step posts the reasoning as a PR comment after publish.

When `prompt` is set, the prompt file is read, merged context (global + execution + task) is appended as a
`## Context` section, and the result is written to a temporary file passed to the agent command.

---

## `git`

Git automation for an execution. Configured as a nested block inside an execution.

```yaml
git:
  branch:
    name: propagate/my-feature
    # OR name_key: :branch-name
    # OR name_template: "feature-{signal[pr_number]}"
    base: main
    reuse: true
  commit:
    message_source: commit-msg        # OR message_key: :commit-message
                                      # OR message_template: "feat: PR #{signal[pr_number]}"
  push:
    remote: origin
  pr:
    base: main
    draft: false
    title_key: :pr-title
    # OR title_template: "PR #{signal[pr_number]}"
    body_key: :pr-body
    # OR body_template: "Implements PR #{signal[pr_number]}"
```

### `git.branch`

Controls branch creation and checkout before sub-tasks run.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | No | `propagate/{execution_name}` | Branch name. Mutually exclusive with `name_key` and `name_template`. |
| `name_key` | string | No | — | Context key (must start with `:`) whose value becomes the branch name. Mutually exclusive with `name` and `name_template`. |
| `name_template` | string | No | — | Template rendered at runtime. Mutually exclusive with `name` and `name_key`. |
| `base` | string | No | Current branch | Base ref to branch from when creating a new branch. |
| `reuse` | boolean | No | `true` | Reuse an existing branch if it already exists. If `false` and the branch exists, the run fails. |

### `git.commit`

Controls how commits are created after sub-tasks produce file changes.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message_source` | string | One of | Name of a context source whose command output becomes the commit message. |
| `message_key` | string | One of | Context key (must start with `:`) whose value becomes the commit message. |
| `message_template` | string | One of | Template rendered at runtime into the commit message. |

Exactly **one** of `message_source`, `message_key`, or `message_template` must be set.

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
| `title_key` | string or mapping | No | First line of commit message | Context key reference for the PR title. Bare strings remain execution-scoped; mapping form can declare `scope` and optional `task`. Mutually exclusive with `title_template`. |
| `title_template` | string | No | First line of commit message | Template rendered at runtime for the PR title. Mutually exclusive with `title_key`. |
| `body_key` | string or mapping | No | Remaining commit message lines | Context key reference for the PR body. Bare strings remain execution-scoped; mapping form can declare `scope` and optional `task`. Mutually exclusive with `body_template`. |
| `body_template` | string | No | Remaining commit message lines | Template rendered at runtime for the PR body. Mutually exclusive with `body_key`. |
| `number_key` | string or mapping | No | — | Context key reference where the PR number is stored after creation. Bare strings remain execution-scoped; mapping form can declare `scope` and optional `task`. |

PRs are created via `gh pr create`.

Template fields support:

- `{signal[field]}` for active signal payload values
- `{context[key]}` for the current execution context
- `{context[execution-or-execution/task][key]}` for another execution/task context
- `{execution.name}` for the current execution name

---

## `propagation`

Defines DAG edges that activate executions after other executions complete.

```yaml
propagation:
  triggers:
    - after: triage-change
      run: update-docs
      when_context: :ready-for-docs   # optional
      on_signal: repo-change          # optional
      when:                           # optional, requires on_signal
        urgent: true
```

### Trigger fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `after` | string | Yes | Execution that must complete to fire this trigger. Must reference a defined execution. |
| `run` | string | Yes | Execution to activate. Must reference a defined execution. |
| `when_context` | string | No | Context gate evaluated against the completed execution's context. Uses the same syntax as sub-task `when`: `:key` requires a non-empty key, `!:key` requires it to be missing or empty. |
| `on_signal` | string | No | Only fire if this signal type was received. Must reference a defined signal. |
| `when` | mapping | No | Payload field-value filter. Requires `on_signal`. Field names must exist in the signal's payload. Values can be literals or matcher objects such as `{ equals_context: :key }`. |

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
  - 'mkdir -p .propagate-context-propagate && echo "done" > .propagate-context-propagate/status'
```

### Git commands

Prefix with `git:` for git operations. These require a `git` block on the execution.

| Command | Arguments | Description |
|---------|-----------|-------------|
| `git:branch` | — | Create or checkout the configured branch. |
| `git:commit` | — | Stage all changes and commit. |
| `git:publish` | — | Run commit, push, and PR creation in order. |
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
  - git:publish
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
| `PROPAGATE_CONTEXT_ROOT` | `.propagate-context-{config_stem}` (relative to config directory) | Root directory for the context store. Namespaced by config file stem (e.g. `.propagate-context-propagate` for `propagate.yaml`). |
| `PROPAGATE_CLONE_DIR` | System temp directory | Directory for cloned repositories. Overrides the YAML `clone_dir` key. |

### Set at runtime

These are set by Propagate when running hooks and agent commands:

| Variable | Description |
|----------|-------------|
| `PROPAGATE_CONFIG_DIR` | Absolute path to the directory containing the config YAML file. Useful for referencing scripts relative to the config. |
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
- Sub-tasks with `wait_for_signal` must not have `prompt`, `on_failure`, or `must_set`.
- `must_set` entries must be valid context keys.
- Route `goto` targets must reference a sub-task ID defined earlier in the same execution.
- `max_goto` requires `goto` to be set on the same sub-task and must be a positive integer.
- Direct `goto` (without `wait_for_signal`) requires `when` to prevent unconditional loops.
- Propagation `when` requires `on_signal` to be set.
- `when` field names must exist in the referenced signal's payload definition.
- `depends_on` entries must reference defined executions and cannot self-reference.
- Repository `ref` is only valid with `url`, not `path`.

### DAG validation

The execution graph (formed by `depends_on` and propagation triggers) must be acyclic. Cycles are detected at config
load time and cause a validation error with the cycle path.

---

## State and Resumption

Run state is persisted to `.propagate-state-{name}.yaml` in the config file directory. The state file is retained after
both interrupted and successful runs and is only removed by `propagate clear`. Use `--resume` to continue an
interrupted run. Completed phases and tasks are skipped on resume.

### Forced Resume

Use `--resume <execution>` or `--resume <execution>/<task>` to force resume from a specific point in the DAG:

```bash
# Resume from the start of the "suggest" execution
propagate run --config config.yaml --resume suggest

# Resume from task "wait-for-verdict" in execution "suggest"
propagate run --config config.yaml --resume suggest/wait-for-verdict
```

This rewrites the saved state so that all executions before the target are marked as completed, and (when a task is
specified) all sub-tasks before the target task are marked as completed. The target execution's `before` hooks are
skipped when resuming from a specific task. This is useful during development/debugging when you want to retry a
specific step without re-running the entire pipeline.

---

## CLI Reference

```bash
# Run an execution
propagate run --config config.yaml [--execution name] [--signal name] [--signal-payload '{...}'] [--signal-file path] [--resume [execution/task]] [--stop-after name] [--skip execution_or_task ...]

# Send a signal to a running server
propagate send-signal --config config.yaml --signal name [--signal-payload '{...}']
propagate send-signal --config config.yaml --signal-file path

# Manage context
propagate context [--config config.yaml] set <key> <value> [--global | --local]
propagate context [--config config.yaml] get <key> [--global | --local | --task]
propagate context [--config config.yaml] dump

# Run as a long-lived server
propagate serve --config config.yaml [--resume [execution/task]] [--skip execution_or_task ...]

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
| `--resume [target]` | Resume a previously interrupted run. Without a target, resumes from saved state. With `execution` or `execution/task`, forces resume from that point. |
| `--stop-after` | Stop the run after the named execution completes. Upstream executions and propagation triggers fire normally, but the scheduler exits before running any execution beyond the named one. Run state is preserved, so the remaining executions can be completed with `--resume`. |
| `--skip` | Skip an execution or task. Use `execution_name` to skip an entire execution, or `execution_name/task_id` to skip a single task. Repeatable. Skipped executions are never run, and downstream executions that depend on them stay pending. Not persisted — must be re-supplied on resume. |

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
| `-f`, `--force` | Also delete cloned repositories recorded in the run state file. Only directories marked as propagate-managed clones are removed. |

Removes the `.propagate-context-{name}/` directory and the `.propagate-state-{name}.yaml` file associated with the config. With `-f`, also removes cloned repository directories that were created during the run.

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

agents:
  default:
    command: "claude -p {prompt_file}"
  agent-easy:
    command: "claude -p {prompt_file} --easy"
  agent-hard:
    command: "claude -p {prompt_file} --hard"
agent: default

repositories:
  workspace:
    path: ./repos/workspace
  core-api:
    path: ./repos/core-api
  docs-site:
    path: ./repos/docs-site

context_sources:
  change-summary:
    command: 'cat .propagate-context-propagate/:signal.branch'
  commit-msg:
    command: 'echo "docs: update generated content"'

signals:
  include:
    - ./signals/github-signals.yaml
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
          - 'echo "triage failed" > .propagate-context-propagate/failure'

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
