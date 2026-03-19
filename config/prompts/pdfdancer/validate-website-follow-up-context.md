# Validate Website Follow-Up Context

This task must fail fast unless the website run is continuing from the approved api-docs PR created for the same backend PR.

## Inputs

Read the stored workflow context and the relevant PRs:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task implement-approved-api-docs-updates | xargs)"
API_DOCS_PR_NUMBER="$(propagate context get :api-docs-pr-number --task implement-approved-api-docs-updates | xargs)"
SIGNAL_REPOSITORY="$(propagate context get :signal.repository | xargs)"
SIGNAL_LABEL="$(propagate context get :signal.label | xargs)"
SIGNAL_PR_NUMBER="$(propagate context get :signal.pr_number | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,url
gh pr view "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs --json number,title,url,labels,state,headRefName,baseRefName
```

## Validation Rules

Treat the workflow state as valid only if all of these are true:

- `BACKEND_PR_NUMBER` is non-empty
- `API_DOCS_PR_NUMBER` is non-empty
- `SIGNAL_REPOSITORY` is exactly `MenschMachine/pdfdancer-api-docs`
- `SIGNAL_LABEL` is exactly `approved`
- `SIGNAL_PR_NUMBER` is exactly `API_DOCS_PR_NUMBER`

## Task

Perform the validation deterministically. If any rule fails, stop immediately and fail the task before any website branch is created.

If validation succeeds, do not edit code in this task. This task is only the workflow safety gate.
