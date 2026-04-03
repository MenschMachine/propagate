# Git Automation

Git operations are driven by explicit hook commands (`git:branch`, `git:commit`, `git:publish`, `git:push`, `git:pr`) placed in execution or sub-task hooks. The `git:` block on an execution declares configuration; the commands control when each operation runs.

## Hook Commands

| Command | Effect |
|---------|--------|
| `git:branch` | Verify git repo, capture starting branch, ensure clean tree, create/checkout target branch, sync reused branches with remote |
| `git:commit` | Stage all changes and commit; **skipped silently if the tree is clean** |
| `git:publish` | Run `git:commit`, `git:push`, and `git:pr` in order |
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
    name_key: :branch-name    # optional; read branch name from context key (mutually exclusive with name)
    # OR
    name_template: "feature-{signal[pr_number]}"
    base: main                # optional; base ref when creating a new branch
                              # defaults to the starting branch
    reuse: true               # default: true — reuse existing branch
                              # set to false to error if the branch already exists

  commit:                     # required
    message_source: my-source # name of a context_source whose output becomes the commit message
    # OR
    message_key: :my-key      # a ':'-prefixed context key holding the commit message
    # OR
    message_template: "feat: PR #{signal[pr_number]}"

  push:                       # omit to skip push (and PR)
    remote: origin

  pr:                         # omit to skip PR creation; requires push to be configured
    base: main                # optional override for PR base branch
                              # defaults to: pr.base → branch.base → starting branch
    draft: false              # default: false
    title_key: :pr-title      # optional ':'-prefixed context key for PR title
    # OR
    title_template: "PR #{signal[pr_number]}"
    body_key: :pr-body        # optional ':'-prefixed context key for PR body
    # OR
    body_template: "Implements PR #{signal[pr_number]}"
    number_key: :pr-number    # optional ':'-prefixed context key; PR number extracted from URL and stored here
```

### Constraints

- `git.branch.name`, `git.branch.name_key`, and `git.branch.name_template` are mutually exclusive — at most one may be set.
- `git.branch.name_key` must use a `:` prefix (reserved context key).
- `git.commit` must define exactly one of `message_source`, `message_key`, or `message_template`.
- `message_key` must use a `:` prefix (reserved context key).
- `git.pr` requires `git.push` to also be configured.
- `git.pr.number_key` must use a `:` prefix (reserved context key).
- `title_key` / `title_template` and `body_key` / `body_template` are mutually exclusive pairs.

## Commit message

- `message_source` — runs the named `context_source` shell command and uses its stdout.
- `message_key` — reads the value from the execution's context store.
- `message_template` — renders a template string at runtime.

By default the message is split on the first line: line 1 becomes the PR title, the rest becomes the PR body.

### PR title and body overrides

Set `title_key` and/or `body_key` in the `pr:` block to read title/body from the execution context store instead:

```yaml
pr:
  title_key: :pr-title   # reads PR title from the execution context store
  body_key: :pr-body     # reads PR body from the execution context store
```

Both are optional `:` -prefixed context keys. When omitted the commit-message split applies as before.

You can also use `title_template` and `body_template` for simple declarative strings.

### Dynamic branch name (`name_key`)

Use `name_key` to read the branch name from a context key at runtime. This is useful when the branch name is generated dynamically (e.g. by an agent).

```yaml
git:
  branch:
    name_key: :branch-name   # agent writes this key before git:branch runs
    base: main
```

`name_key` and `name` are mutually exclusive. When neither is set, the default `propagate/{execution-name}` is used.

### Runtime templates

Template fields support:

- `{signal[field]}` for active signal payload values
- `{context[key]}` for the current execution context
- `{context[execution-or-execution/task][key]}` for another execution/task context
- `{execution.name}` for the current execution name

Example:

```yaml
git:
  branch:
    name_template: "docs/pr-{signal[pr_number]}"
  commit:
    message_template: "docs: update PR #{signal[pr_number]}"
  pr:
    body_template: "Follow-up for PR #{signal[pr_number]}"
```

### PR number capture (`number_key`)

Use `number_key` on `git.pr` to store the PR number in context after creation. The number is extracted from the PR URL returned by `gh pr create`.

```yaml
git:
  pr:
    base: main
    number_key: :pr-number   # stores e.g. "42" after PR creation
```

## Branch selection

| Scenario | Behaviour |
|----------|-----------|
| `name` is set and branch doesn't exist | Create branch from `base` (or starting branch) |
| `name` is set, branch exists, `reuse: true` | Check out existing branch, fetch matching remote branch, and fast-forward if behind |
| `name` is set, branch exists, `reuse: false` | Error |
| `name` is omitted (no `name_key` / `name_template` either) | Use `propagate/{execution-name}` as the branch name |
| `name_key` is set | Read branch name from context key |
| `name_template` is set | Render branch name from template |
| Target branch is already checked out | Reuse it, fetch matching remote branch, and fast-forward if behind |

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

## Resume behaviour

On `--resume`, git state is restored from the execution context store rather than re-running `git:branch`. Three fields are persisted as context keys when set:

| Context key | Set by | Consumed by |
|---|---|---|
| `:git.starting_branch` | `git:branch` | `git:pr` (as PR base fallback) |
| `:git.selected_branch` | `git:branch` | `git:push`, `git:pr` |
| `:git.commit_message` | `git:commit` | `git:pr` (as PR title/body source) |

This means `git:push` and `git:pr` work correctly on resume even though `git:branch` and `git:commit` are skipped (they were already completed). Execution context written by earlier sub-tasks is also preserved — context is only cleared for fresh runs, not resumed ones.

## `.env` exclusion

Propagate automatically excludes `.env` files from commits. The `git:commit` command uses `git add -A -- . :!.env :!**/.env`, which prevents `.env` files at any directory level from being staged regardless of the repository's `.gitignore` settings. This protects secrets and API keys from being accidentally committed to cloned repositories.

## Authentication

Propagate supports two authentication methods for HTTPS git operations:

1. **`GITHUB_TOKEN` environment variable (recommended for servers):** When set, the token is injected into clone URLs as `https://x-access-token:TOKEN@github.com/...`. The token is never logged.
2. **`gh` CLI credential helper (for local development):** After cloning, the repo's local git config is set to use `gh auth git-credential` for subsequent operations (`push`, `fetch`, PR creation).

When cloning a URL repository, SSH URLs (`git@github.com:owner/repo.git`) are automatically converted to HTTPS.

For server deployments, set `GITHUB_TOKEN` in the `.env` file. For local development, make sure `gh auth login` has been run.

## Notes

- `git:branch` must run before `git:push` or `git:pr` (it captures the branch name used by those commands).
- `git:pr-*` commands don't require `git:branch` — they operate on whatever PR exists for the current branch via `gh`.
- `git:commit` silently skips if the working tree is clean — safe to always include after any sub-task.
- If `git:push` is omitted from a config with `pr:`, `git:pr` will still attempt PR creation using the current branch.
- Resolved label values are validated at runtime — empty strings and values containing commas or newlines are rejected.
