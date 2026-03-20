# Validate API PR Trigger

This task must fail fast unless the triggering signal is the expected merged API PR event for this workflow.

## Inputs

Read the signal context and source PR:

```bash
PR_NUMBER="$(propagate context get :signal.pr_number | xargs)"
REPOSITORY="$(propagate context get :signal.repository | xargs)"
MERGED="$(propagate context get :signal.merged | xargs)"
gh pr view "$PR_NUMBER" --repo MenschMachine/pdfdancer-api --json number,title,body,url,labels,state,headRefName,baseRefName
```

## Validation Rules

Treat the trigger as valid only if all of these are true:

- `REPOSITORY` is exactly `MenschMachine/pdfdancer-api`
- `MERGED` is exactly `True`
- `PR_NUMBER` is non-empty and resolves to an existing API pull request

## Task

Perform the validation deterministically. If any rule fails, stop immediately and fail the task before any branch is created.

If validation succeeds, do not edit code in this task. This task is only the workflow safety gate.
