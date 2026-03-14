# Git Automation

Git operations are driven by explicit hook commands (`git:branch`, `git:commit`, `git:push`, `git:pr`) placed in execution or sub-task hooks. The `git:` block on an execution declares configuration; the commands control when each operation runs.

## Hook Commands

| Command | Effect |
|---------|--------|
| `git:branch` | Verify git repo, capture starting branch, ensure clean tree, create/checkout target branch |
| `git:commit` | Stage all changes and commit; **skipped silently if the tree is clean** |
| `git:push` | Push the current branch to the configured remote |
| `git:pr` | Create a pull request via `gh pr create` |

### PR Checks Command

| Command | Args | Effect |
|---------|------|--------|
| `git:pr-checks-wait` | `<:result-key> <:status-key> [interval] [timeout]` | Poll GitHub Actions checks until complete, store results and pass/fail status in context keys |

Polls `gh pr checks`, filters to GitHub Actions only (entries with a non-empty `workflow.name`), and waits until all are completed.

- `:result-key` — stores filtered checks as JSON
- `:status-key` — writes `"true"` if all checks passed, `""` (empty string) if any failed
- `interval` — poll interval in seconds (default: 10)
- `timeout` — max wait in seconds (default: 1800 = 30 minutes)

The command **never raises** on check failures — use the `when` field on subtasks to branch based on the status key. Timeout still raises `PropagateError` (that's a real error, not a branch condition).

If the repository has no GitHub Actions workflows, no action checks will ever appear and the command will wait until timeout.

```yaml
sub_tasks:
  - id: wait-ci
    before:
      - git:pr-checks-wait :check-results :checks-passed 10 1800

  - id: handle-success
    when: ":checks-passed"
    prompt: ./prompts/on-pass.md

  - id: handle-failure
    when: "!:checks-passed"
    prompt: ./prompts/on-fail.md
```

### Conditional Subtask Execution (`when`)

Subtasks support a `when` field that references a context key. The subtask is skipped if the condition is falsy.

- `when: ":key"` — run if key exists and has a non-empty value
- `when: "!:key"` — run if key is missing or has an empty value

The `when` condition resolves against **execution-scoped** context only (keys written to the execution's context directory). Global or task-scoped keys are not checked.

On resume, skipped-via-`when` subtasks are re-evaluated — the condition is checked again against the current context state.

### PR Label and Comment Commands

These commands manage labels and comments on the current PR via `gh`. They operate on whatever PR exists for the current branch and do not require `git:branch`. Arguments are passed inline after the command name.

| Command | Args | Effect |
|---------|------|--------|
| `git:pr-labels-add` | `<label\|:key> [...]` | Add one or more labels to the PR |
| `git:pr-labels-remove` | `<label\|:key> [...]` | Remove one or more labels from the PR |
| `git:pr-labels-list` | `<:key>` | Read current PR labels (JSON) into context key |
| `git:pr-comment-add` | `<:key>` | Add a comment; body read from context key |
| `git:pr-comments-list` | `<:key>` | Read PR comments (JSON) into context key |

Plain label strings are used as-is. `:key` args are resolved from the execution context store at runtime.

These commands can appear in any hook list: execution `before`/`after`/`on_failure`, or sub-task `before`/`after`/`on_failure`.

## Config reference

```yaml
git:
  branch:
    name: my-branch-name      # optional; defaults to "propagate/{execution-name}"
    base: main                # optional; base ref when creating a new branch
                              # defaults to the starting branch
    reuse: true               # default: true — reuse existing branch
                              # set to false to error if the branch already exists

  commit:                     # required
    message_source: my-source # name of a context_source whose output becomes the commit message
    # OR
    message_key: :my-key      # a ':'-prefixed context key holding the commit message

  push:                       # omit to skip push (and PR)
    remote: origin

  pr:                         # omit to skip PR creation; requires push to be configured
    base: main                # optional override for PR base branch
                              # defaults to: pr.base → branch.base → starting branch
    draft: false              # default: false
    title_key: :pr-title      # optional ':'-prefixed context key for PR title
    body_key: :pr-body        # optional ':'-prefixed context key for PR body
```

### Constraints

- `git.commit` must define exactly one of `message_source` or `message_key` — not both, not neither.
- `message_key` must use a `:` prefix (reserved context key).
- `git.pr` requires `git.push` to also be configured.

## Commit message

- `message_source` — runs the named `context_source` shell command and uses its stdout.
- `message_key` — reads the value from the execution's context store.

By default the message is split on the first line: line 1 becomes the PR title, the rest becomes the PR body.

### PR title and body overrides

Set `title_key` and/or `body_key` in the `pr:` block to read title/body from the execution context store instead:

```yaml
pr:
  title_key: :pr-title   # reads PR title from the execution context store
  body_key: :pr-body     # reads PR body from the execution context store
```

Both are optional `:` -prefixed context keys. When omitted the commit-message split applies as before.

## Branch selection

| Scenario | Behaviour |
|----------|-----------|
| `name` is set and branch doesn't exist | Create branch from `base` (or starting branch) |
| `name` is set, branch exists, `reuse: true` | Check out existing branch |
| `name` is set, branch exists, `reuse: false` | Error |
| `name` is omitted | Use `propagate/{execution-name}` as the branch name |
| Target branch is already checked out | Use it as-is, skip checkout |

## Example

```yaml
context_sources:
  commit-msg:
    command: echo "propagate: update sdk"

executions:
  update-sdk:
    repository: sdk-python
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
        draft: false
    before:
      - git:branch         # prepare branch before any sub-task
    sub_tasks:
      - id: implementation
        prompt: ./prompts/implement.md
        after:
          - git:commit      # commit after this sub-task
      - id: review
        prompt: ./prompts/review.md
        # no git here — review runs on committed state
    after:
      - git:push            # push after all sub-tasks
      - git:pr              # open PR at the end
```

## PR label and comment examples

Labels accept plain strings or `:key` context references. Comment and list commands always use `:key`.

```yaml
after:
  - git:push
  - git:pr
  - git:pr-labels-add bug enhancement :extra-label  # mix of fixed and dynamic
  - git:pr-labels-remove in-progress                 # remove a label
  - git:pr-comment-add :review-summary               # post comment from context
  - git:pr-labels-list :current-labels               # read labels into context
  - git:pr-comments-list :all-comments               # read comments into context
```

### Full workflow: create PR, label it, post a summary comment

```yaml
executions:
  update-sdk:
    repository: sdk-python
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
      - id: summarize
        prompt: ./prompts/summarize.md
    after:
      - git:push
      - git:pr
      - git:pr-labels-add :pr-label
      - git:pr-comment-add :pr-summary
```

## Notes

- `git:branch` must run before `git:push` or `git:pr` (it captures the branch name used by those commands).
- `git:pr-*` commands don't require `git:branch` — they operate on whatever PR exists for the current branch via `gh`.
- `git:commit` silently skips if the working tree is clean — safe to always include after any sub-task.
- If `git:push` is omitted from a config with `pr:`, `git:pr` will still attempt PR creation using the current branch.
- Resolved label values are validated at runtime — empty strings and values containing commas or newlines are rejected.
