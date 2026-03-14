# Git Automation

Adding a `git:` block to an execution enables automatic branch management, committing, pushing, and PR creation around the sub-task run.

## TODO

- **Push conflict resolution**: Push failures (e.g. remote has new commits) are fatal — the execution errors out. No pull, rebase, or retry is attempted.
- **PR title/description**: Both are derived by splitting the commit message on the first newline. Line 1 → title, remainder → body. No templating or generation — whatever the `message_source` command or `message_key` value produces is used verbatim.

## Execution flow

When `git:` is present, the execution follows this sequence:

1. Verify the working directory is inside a git repository
2. Capture the current (starting) branch
3. Assert a clean working tree — dirty tree aborts
4. Create or checkout the target branch
5. Run sub-tasks normally
6. If the working tree has changes: commit → push → open PR
7. If no changes were made, skip commit/push/PR entirely

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
```

### Constraints

- `git.commit` must define exactly one of `message_source` or `message_key` — not both, not neither.
- `message_key` must use a `:` prefix (reserved context key).
- `git.pr` requires `git.push` to also be configured.

## Commit message

The commit message is loaded at publish time, after sub-tasks complete:

- `message_source` — runs the named `context_source` shell command and uses its stdout.
- `message_key` — reads the value from the execution's context store.

The message is split on the first line: line 1 becomes the PR title, the rest becomes the PR body.

## Branch selection

| Scenario | Behaviour |
|----------|-----------|
| `name` is set and branch doesn't exist | Create branch from `base` (or starting branch) |
| `name` is set, branch exists, `reuse: true` | Check out existing branch |
| `name` is set, branch exists, `reuse: false` | Error |
| `name` is omitted | Use `propagate/{execution-name}` as the branch name |
| Target branch is already checked out | Use it as-is, skip checkout |

## Minimal example

```yaml
context_sources:
  commit-msg:
    command: echo "propagate: update sdk"

executions:
  update-sdk:
    repository: sdk-python
    sub_tasks:
      - id: implementation
        prompt: ./prompts/implement.md
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
```

## Full example with context key

```yaml
executions:
  update-sdk:
    repository: sdk-python
    sub_tasks:
      - id: implementation
        prompt: ./prompts/implement.md
        hooks:
          after: |
            propagate context set :commit-message "feat: update sdk bindings"
    git:
      branch:
        name: propagate/sdk-update
        base: main
        reuse: true
      commit:
        message_key: :commit-message
      push:
        remote: origin
      pr:
        draft: true
```
