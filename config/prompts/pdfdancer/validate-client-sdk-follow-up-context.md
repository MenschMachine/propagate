This execution must continue from the approved upstream API work for the same source PR.

Validate:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,url,state,mergedAt
  API_PR_NUMBER="$(propagate context get :api-pr-number --task implement-pdfdancer-api | xargs)"
else
  API_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
fi
gh pr view "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json number,title,url,labels,state,headRefName,baseRefName
```

Fail fast unless:

- the API PR exists
- if the source is backend-origin, the backend PR exists and is merged
- the API PR is the approved upstream implementation for this run

Do not modify any files, write any code, or change context. This task is validation only — a workflow safety gate.
