This execution must continue from the approved `pdfdancer-api` PR for the same backend PR.

Validate:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
API_PR_NUMBER="$(propagate context get :api-pr-number --task implement-pdfdancer-api | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,url,state,mergedAt
gh pr view "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json number,title,url,labels,state,headRefName,baseRefName
```

Fail fast unless:

- the backend PR exists and is merged
- the API PR exists
- the API PR is the approved upstream implementation for this backend PR

Do not modify any files, write any code, or change context. This task is validation only — a workflow safety gate.
