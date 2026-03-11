# README - Propagate

## Data Model

### Signals

Can be:
	- PR created
	- PR label changed
	- PR closed and merged
	- PR closed not merged
	- Manual trigger
	- Upstream task completed

## Executions

Executions are agent tasks in a specific repository and with a configured prompt and context information.
Executions can fail or succeed.
They act on github repositories PRs.

If the execution was triggered by a PR, it works on that PR's branch.
If not (downstream or manual without PR context), it creates a branch and opens a PR.

Executions usually consist of 3 sub-tasks:
- implementation
- documentation
- review

This is a default, not hardcoded. Executions can override the sub-task list.

Sub-tasks run in sequence. Each either succeeds (agent completes, hooks exit zero) or fails (hook returns non-zero, agent can't complete). On failure, the execution stops.

Human checkpoints (e.g. reviewing a design before implementation) are modeled as separate executions connected by label signals.

### Git workflow

After every sub-task: commit + push. Always. Not configurable.
Commit message comes from a context source (shell command).
Branch name for new PRs: prefix + slugified PR title from the trigger.

### Labels

Labels are managed imperatively via `gh pr edit` commands in hooks (before, after, on_failure).
Labels drive the state machine and can trigger further executions via pr_label_changed signals.

## Context

Everything an execution knows lives in its context bag — a key-value store with three scopes:
- Local (default): `propagate context set/get key`
- Task-scoped: `propagate context get key --task name`
- Global: `propagate context set/get --global key`

Auto-populated from the trigger signal: pr_number, pr_title, pr_description, pr_branch, pr_labels, diff_summary.
Hooks populate additional values via `propagate context set key value` or `propagate context set :source-name`.

The agent sees all global + local context automatically. Upstream task values must be pulled into local context explicitly via hooks.

There is no separate result block. The context is the result.

## Context Sources

Shell commands that generate runtime context, loaded into context via `:name` shorthand:

propagate context set :openapi-spec

## Hooks

All sub-tasks can have before and after hooks:

before-review: wait-for-github-build.sh

## Repositories

Work is organized by repositories:
- if the work on a repository is completed for all tasks, this can trigger the execution of tasks in other repositories
This is a N-to-N relationship:

on DONE repo-a -> do repo-b and repo-c

as well as

on DONE repo-B and repo-C -> do repo-D


## Edge Cases

Branch already exists
Commit is empty, no files changed
