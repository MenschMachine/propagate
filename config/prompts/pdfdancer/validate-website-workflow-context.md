This execution must continue from the approved `pdfdancer-api-docs` PR for the same backend PR.

Validate:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
API_DOCS_PR_NUMBER="$(propagate context get :api-docs-pr-number --task implement-pdfdancer-api-docs | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,url,state,mergedAt
gh pr view "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs --json number,title,url,labels,state,headRefName,baseRefName
```

Fail fast unless the backend PR exists and is merged and the api-docs PR is the approved upstream docs implementation.
