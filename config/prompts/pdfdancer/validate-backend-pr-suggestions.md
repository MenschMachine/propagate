# Validate Backend PR Suggestion Trigger

This task must fail fast unless the triggering signal is the expected backend PR label event for this workflow.

## Inputs

Read the signal context and source PR:

```bash
PR_NUMBER="$(propagate context get :signal.pr_number | xargs)"
REPOSITORY="$(propagate context get :signal.repository | xargs)"
LABEL="$(propagate context get :signal.label | xargs)"
gh pr view "$PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,body,url,labels,state,headRefName,baseRefName
```

## Validation Rules

Treat the trigger as valid only if all of these are true:

- `REPOSITORY` is exactly `MenschMachine/pdfdancer-backend`
- `LABEL` is exactly `suggestions_needed`
- `PR_NUMBER` is non-empty and resolves to an existing backend pull request

## Task

Perform the validation deterministically. If any rule fails, stop immediately and fail the task before any branch is created.

If validation succeeds, do not edit code in this task. This task is only the workflow safety gate.
