This execution must continue from the approved Python client PR for the same backend PR.

Validate:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
SDK_PR_NUMBER="$(propagate context get :client-python-pr-number --task implement-client-python | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,url,state,mergedAt
gh pr view "$SDK_PR_NUMBER" --repo MenschMachine/pdfdancer-client-python --json number,title,url,labels,state,headRefName,baseRefName
```

Fail fast unless both PRs exist and the SDK PR is the approved upstream Python implementation for this backend PR.
