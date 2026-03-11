# Git Automation Stage 4 Design

## Scope

Stage 4 extends the stage 3 single-repository runtime with optional git automation for successful executions:

- branch creation and selection before sub-tasks run
- commit creation after all sub-tasks succeed
- optional push support
- optional PR creation
- commit-message sourcing from an existing context source

Stage 4 does not add signals, propagation triggers, includes, defaults, repository registries, multi-repo orchestration, parallel execution, or DAG behavior. The implementation stays in `propagate.py`, uses Python 3.10+, `PyYAML`, logging, type hints, f-strings, and preserves the existing `{prompt_file}` agent handoff.

## Config Changes

Bump the schema marker to `version: "4"` and require that exact version in `load_config()`.

Add one optional `git` block under each execution:

```yaml
version: "4"

context_sources:
  commit-message:
    command: ./scripts/write-commit-message.sh

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
      - id: implementation
        prompt: ./prompts/implement-stage5.md
      - id: review
        prompt: ./prompts/review-stage5.md
```

Shape rules:

- `git` is optional. If omitted, the execution keeps stage 3 behavior exactly.
- `git` must be a mapping when provided.
- `git.branch` is required.
- `git.branch.name` is optional. If omitted, Propagate uses `propagate/<execution-name>`.
- `git.branch.base` is optional. If omitted, Propagate uses the branch checked out at run start.
- `git.branch.reuse` is optional and defaults to `true`.
- `git.commit` is required when `git` is configured.
- `git.commit.message_source` is required and must name an existing entry in `context_sources` without the leading `:`.
- `git.push` is optional. If present, it must be a mapping with required field `remote`.
- `git.pr` is optional. If present, `git.push` must also be present.
- `git.pr.base` is optional. If omitted, it defaults to `git.branch.base` if set, otherwise the branch checked out at run start.
- `git.pr.draft` is optional and defaults to `false`.

Stage 4 intentionally does not add git defaults, message templates, labels, reviewers, body templates, provider selection, retries, or fetch policies.

## Git Execution Order

Stage 3 sub-task behavior stays intact. Stage 4 wraps it with execution-level git steps.

If an execution has `git` config, the order is:

1. Resolve the target branch configuration.
2. Verify the invocation working directory is inside a git work tree.
3. Record the branch checked out at run start.
4. Fail if the working tree is dirty before any branch switch or sub-task work.
5. Create or select the target branch.
6. Run all sub-tasks with the existing stage 3 model:
   `before` hooks, prompt augmentation, agent command, `after` hooks, and `on_failure`.
7. If all sub-tasks succeed, inspect the working tree for changes.
8. If changes exist, run the configured commit-message context source, store its output in `.propagate-context/:<source-name>`, and create a commit.
9. If `push` is configured, push the branch.
10. If `pr` is configured, create the PR.

If a sub-task fails, all post-success git steps are skipped. Stage 4 does not add execution-level recovery hooks.

## Branch Naming And Reuse

Branch selection is repository-local and local-branch-first.

Naming rules:

- If `git.branch.name` is set, use it exactly.
- Otherwise derive `propagate/<execution-name>`.
- Validate the final name with `git check-ref-format --branch`.

Base rules:

- If `git.branch.base` is set, use that local branch or ref as the branch-creation start point.
- Otherwise use the branch that was checked out when the run started.
- Stage 4 does not fetch or synchronize refs before branch creation.

Reuse rules:

- If the current branch already matches the target branch, keep it selected.
- If the target branch exists locally and `reuse: true`, checkout that branch and continue.
- If the target branch exists locally and `reuse: false`, fail before running sub-tasks.
- If the target branch does not exist locally, create it from the resolved base ref and checkout it.
- Remote-only branches are not discovered proactively. Any later push rejection is surfaced as a push failure.

The target branch remains checked out after success or failure. Stage 4 does not restore the starting branch automatically.

## Commit Message Sourcing

Stage 4 uses the existing context-source mechanism instead of inventing a second message system.

Commit flow:

1. After all sub-tasks succeed, check whether there are tracked or untracked changes.
2. If there are no changes, log that no commit is needed and skip commit, push, and PR creation.
3. If changes exist, run the context source named by `git.commit.message_source`.
4. Store its stdout in the existing local context bag under `:<source-name>`.
5. Read that stored value back and use it as the exact commit message for `git commit -F <temp-file>`.

Message rules:

- The context source runs after sub-task completion so it can inspect the final repo state.
- The message is taken from stdout exactly as produced.
- An empty or whitespace-only message is an error.
- The first line becomes the PR title when PR creation is enabled.
- Remaining lines, if any, become the PR body.

This keeps commit-message generation aligned with the stage 3 context model while avoiding any new prompt templating feature.

## Dirty Working Tree Policy

Dirty state is checked only for executions that configure `git`.

Before branch setup, Propagate should run the equivalent of `git status --porcelain --untracked-files=all` and fail if any output is present.

Rules:

- Modified tracked files fail the run.
- Staged but uncommitted changes fail the run.
- Untracked files fail the run.
- Propagate does not auto-stash, auto-clean, or auto-commit pre-existing changes.

This keeps stage 4 commits attributable to the current Propagate run and avoids mixing user work with generated changes.

## Failure Behavior

### Branch Setup Failures

Repository checks, dirty-tree failures, invalid branch names, missing base refs, and checkout/create failures stop the execution before any sub-task runs. These surface as `PropagateError`.

### Commit Failures

Commit failures stop the execution and return a non-zero exit status.

Examples:

- the message source command fails
- the stored message is empty
- `git add -A` fails
- `git commit` fails

No push or PR step runs after a commit failure. Any file changes remain in the working tree on the selected branch.

### Push Failures

If commit succeeds but push fails:

- the execution fails
- the local commit remains on the selected branch
- PR creation does not run

### PR Failures

If PR creation fails:

- the execution fails
- the commit and push remain in place
- Propagate does not attempt rollback or PR cleanup

### No-Change Success

If all sub-tasks succeed but the working tree is clean afterward, the execution succeeds with a log message and no commit, push, or PR action.

## PR Creation

PR creation is optional and intentionally narrow in stage 4.

Implementation model:

- Require the GitHub CLI `gh` when `git.pr` is configured.
- Use the selected branch as the PR head.
- Use `git.pr.base` as the PR base.
- Use the commit-message subject as the PR title.
- Use the commit-message body, if present, as the PR body.
- Add `--draft` when `git.pr.draft` is `true`.

Stage 4 does not add labels, reviewers, assignees, provider abstraction, or PR body templating.

## Logging And Error Handling

Keep logging concise and execution-oriented.

`INFO` logging should cover:

- git automation enabled for the execution
- starting branch detection
- dirty-tree check
- branch checkout or creation
- commit-message source execution by source name only
- commit creation
- push destination
- PR creation attempt
- no-change skip behavior

Do not log:

- full commit messages
- prompt contents
- context values
- raw git stdout on success

Error expectations:

- Raise `PropagateError` with user-facing messages for configuration and git command failures.
- Include the execution name and git phase when possible.
- Include the git subprocess exit code when available.
- Capture stderr for failing git and `gh` commands and include a concise trimmed excerpt in the error message when it adds useful context.

Representative messages:

- `Execution 'build-stage5' cannot start git automation: working tree is dirty.`
- `Execution 'build-stage5' failed during branch setup: branch 'propagate/build-stage5' already exists and reuse is disabled.`
- `Execution 'build-stage5' failed during commit-message generation from context source 'commit-message' with exit code 1.`
- `Execution 'build-stage5' failed during push to remote 'origin' with exit code 1.`
- `Execution 'build-stage5' failed during PR creation with exit code 1.`

## Implementation Shape

Keep the change in `propagate.py` with small helpers and new config dataclasses.

Suggested additions:

- `GitBranchConfig`
- `GitCommitConfig`
- `GitPushConfig`
- `GitPrConfig`
- `GitExecutionConfig`
- `parse_git_config(...)`
- `validate_git_references(...)`
- `prepare_git_execution(...)`
- `ensure_clean_working_tree(...)`
- `checkout_or_create_branch(...)`
- `finalize_git_execution(...)`
- `create_commit_from_context_source(...)`
- `push_branch(...)`
- `create_pull_request(...)`
- `run_git_command(...)`

The key boundary is behavioral:

- sub-task hooks and prompt handling remain stage 3 logic
- git automation is execution-level, not sub-task-level
- commit-message generation reuses context sources and the existing `.propagate-context` bag
- stage 4 stays single-repository and local to `Path.cwd()`

## Stage Boundary

Stage 4 explicitly does not add:

- signals or propagation triggers
- includes or defaults
- repository registries or named repositories
- multi-repo orchestration
- DAG scheduling or parallel execution
- retries, auto-stash, auto-fetch, or auto-rebase
- provider-neutral PR APIs

If future config examples mention those capabilities, stage 4 should reject them or ignore them explicitly rather than partially implementing them.
