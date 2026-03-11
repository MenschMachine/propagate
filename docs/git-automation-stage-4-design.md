# Git Automation Stage 4 Design

## Scope

Stage 4 adds optional, repository-local git automation on top of the stage 3 runtime:

- branch creation and checkout before sub-tasks run
- one commit after the execution succeeds
- optional push
- optional PR creation
- commit-message sourcing from an existing context source

Stage 4 keeps the stage 3 execution model intact:

- sub-tasks still run sequentially
- `before`, `after`, and `on_failure` hooks keep their current meaning
- prompt paths still resolve relative to the config file
- context still lives in `.propagate-context` under `Path.cwd()`
- the agent handoff still uses `{prompt_file}`

Stage 4 does not add signals, propagation triggers, includes, defaults, repository registries, multi-repo orchestration, DAG execution, retries, or provider abstraction.

## Config Shape

Bump the config schema to `version: "4"` and require that exact value in `load_config()`.

Add an optional `git` block under each execution:

```yaml
version: "4"

context_sources:
  commit-message:
    command: ./scripts/generate-commit-message.sh

executions:
  build-stage5:
    git:
      branch:
        name: propagate/build-stage5
        base: main
        reuse: true
      commit:
        message_source: commit-message
      push:
        remote: origin
      pr:
        base: main
        draft: false
    sub_tasks:
      - id: design
        prompt: ./prompts/design-stage5.md
      - id: implement
        prompt: ./prompts/implement-stage5.md
      - id: review
        prompt: ./prompts/review-stage5.md
```

Validation rules:

- `git` is optional. If omitted, the execution behaves exactly as stage 3.
- `git` must be a mapping.
- `git.branch` is required when `git` is present.
- `git.branch.name` is optional. Default: `propagate/<execution-name>`.
- `git.branch.base` is optional. Default: the branch checked out when the run starts.
- `git.branch.reuse` is optional. Default: `true`.
- `git.commit` is required when `git` is present.
- `git.commit.message_source` is required and must reference an existing `context_sources` entry by name, without a leading `:`.
- `git.push` is optional. If present, it must be a mapping with required field `remote`.
- `git.pr` is optional. If present, `git.push` must also be present.
- `git.pr.base` is optional. Default: `git.branch.base` if set, otherwise the branch detected at run start.
- `git.pr.draft` is optional. Default: `false`.

Stage 4 intentionally does not add message templates, labels, reviewers, assignees, body templates, retries, fetch policies, or global git defaults.

## Runtime Order

If an execution does not declare `git`, run the existing stage 3 flow unchanged.

If an execution declares `git`, the execution order becomes:

1. Parse and validate the git config.
2. Verify `Path.cwd()` is inside a git work tree.
3. Detect the branch checked out at run start.
4. Check that the working tree is clean before any git automation or sub-task work.
5. Resolve and checkout or create the target branch.
6. Run sub-tasks using the stage 3 model:
   `before` hooks, prompt augmentation, agent command, `after` hooks, `on_failure` hooks.
7. If any sub-task fails, stop immediately and skip commit, push, and PR steps.
8. If all sub-tasks succeed, inspect the working tree for changes.
9. If changes exist, load the configured commit-message context source and create one commit.
10. If `push` is configured, push the selected branch.
11. If `pr` is configured, create a PR.

Git automation is execution-level, not sub-task-level. Stage 4 creates at most one commit per successful execution.

## Branch Naming And Reuse

Branch naming rules:

- If `git.branch.name` is set, use it exactly.
- Otherwise use `propagate/<execution-name>`.
- Validate the final name with `git check-ref-format --branch`.

Base rules:

- If `git.branch.base` is set, use that ref as the start point for a new branch.
- Otherwise use the branch detected at run start.
- Stage 4 does not fetch, pull, or rebase automatically.

Reuse rules:

- If the current branch already matches the target branch, keep it checked out.
- If the target branch exists locally and `reuse` is `true`, checkout that branch.
- If the target branch exists locally and `reuse` is `false`, fail before sub-tasks run.
- If the target branch does not exist locally, create it from the resolved base ref and checkout it.
- Remote-only branches are not discovered in advance. If a later push is rejected, that is a push failure.

The selected branch remains checked out when the run ends. Stage 4 does not restore the starting branch.

## Commit Message Sourcing

Stage 4 reuses the existing stage 3 context-source mechanism rather than adding a second message system.

Commit flow:

1. After all sub-tasks succeed, run a dirty check.
2. If there are no tracked or untracked changes, log that no commit is needed and stop git automation successfully.
3. If changes exist, run the context source named by `git.commit.message_source`.
4. Store its stdout in the local context bag under `:<source-name>` using the same write path as stage 3 context-source hooks.
5. Read that stored value and pass it to `git commit -F <temp-file>`.

Rules:

- The message source runs after sub-tasks finish so it can inspect the final repo state.
- The stored value is used exactly as produced; no trimming except validation for empty or whitespace-only output.
- Empty or whitespace-only output is an error.
- The first line becomes the PR title when PR creation is enabled.
- Remaining lines, if present, become the PR body.

This keeps commit metadata inside the same `.propagate-context` model already used elsewhere in the runtime.

## Dirty Working Tree Policy

Dirty-tree validation only applies when an execution has `git` configured.

Before branch setup, run the equivalent of:

```sh
git status --porcelain --untracked-files=all
```

If any output is present, fail the execution before running sub-tasks.

This includes:

- modified tracked files
- staged but uncommitted changes
- untracked files

Stage 4 does not auto-stash, auto-clean, or auto-commit pre-existing changes.

## Failure Behavior

Branch setup failures:

- not a git repository
- invalid branch name
- missing base ref
- checkout failure
- target branch already exists with `reuse: false`
- dirty working tree before start

These fail the execution before any sub-task runs and surface as `PropagateError`.

Commit failures:

- message-source command exits non-zero
- stored message is empty
- `git add -A` fails
- `git commit` fails

These fail the execution after sub-tasks complete. The working tree stays as-is on the selected branch. Push and PR steps do not run.

Push failures:

- fail the execution
- keep the local commit in place
- skip PR creation

PR creation failures:

- fail the execution
- keep the commit and any successful push in place
- do not attempt rollback or PR cleanup

No-change success:

- if sub-tasks succeed and the working tree is clean afterward, the execution succeeds
- no commit, push, or PR is attempted

## PR Creation

PR creation is optional and intentionally narrow in stage 4.

Implementation model:

- require the GitHub CLI `gh` when `git.pr` is configured
- use the current branch as the PR head
- use `git.pr.base` as the PR base
- use the commit-message subject as the PR title
- use the remaining commit-message lines as the PR body
- add `--draft` when `git.pr.draft` is `true`

Stage 4 does not add labels, reviewers, assignees, provider-neutral APIs, or PR body templating.

## Logging And Errors

Use `logging`, not `print()`.

`INFO` logs should cover:

- git automation enabled for the execution
- detected starting branch
- dirty-tree check
- branch checkout or creation
- commit-message source execution by source name only
- commit creation
- push destination
- PR creation attempt
- no-change skip behavior

Do not log:

- prompt contents
- context values
- commit message contents
- raw success stdout from git or `gh`

Error handling rules:

- Raise `PropagateError` for invalid config and user-facing git failures.
- Include the execution name and the failing git phase when possible.
- Include subprocess exit codes when available.
- Capture stderr for failed git and `gh` commands and include a short trimmed excerpt when useful.

Representative errors:

- `Execution 'build-stage5' cannot start git automation: working tree is dirty.`
- `Execution 'build-stage5' failed during branch setup: branch 'propagate/build-stage5' already exists and reuse is disabled.`
- `Execution 'build-stage5' failed during commit-message generation from context source 'commit-message' with exit code 1.`
- `Execution 'build-stage5' failed during push to remote 'origin' with exit code 1.`
- `Execution 'build-stage5' failed during PR creation with exit code 1.`

## Implementation Shape

Keep the implementation in `propagate.py` with small helpers and explicit dataclasses.

Suggested additions:

- `GitBranchConfig`
- `GitCommitConfig`
- `GitPushConfig`
- `GitPrConfig`
- `GitExecutionConfig`
- `parse_git_config(...)`
- `prepare_git_execution(...)`
- `ensure_clean_working_tree(...)`
- `checkout_or_create_branch(...)`
- `finalize_git_execution(...)`
- `create_commit_from_context_source(...)`
- `push_branch(...)`
- `create_pull_request(...)`
- `run_git_command(...)`

The important boundary is behavioral:

- stage 3 hook and prompt handling remains unchanged
- git automation wraps the execution, not each sub-task
- commit-message generation reuses context sources and `.propagate-context`
- everything remains local to the single repository at `Path.cwd()`

## Stage Boundary

Stage 4 explicitly does not add:

- signals or propagation triggers
- includes or defaults
- repository registries or named repositories
- multi-repo orchestration
- DAG scheduling or parallel execution
- automatic fetch, pull, stash, rebase, or retry behavior
- provider abstraction beyond the narrow `gh`-based PR step
