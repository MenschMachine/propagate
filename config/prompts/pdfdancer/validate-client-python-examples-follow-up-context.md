This execution must continue from the approved Python client PR for the same source PR.

Validate:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,url,state,mergedAt
else
  API_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
  gh pr view "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json number,title,url,state,mergedAt
fi
SDK_PR_NUMBER="$(propagate context get :client-python-pr-number --task implement-client-python | xargs)"
gh pr view "$SDK_PR_NUMBER" --repo MenschMachine/pdfdancer-client-python --json number,title,url,labels,state,headRefName,baseRefName
```

Fail fast unless the source PR exists and the SDK PR is the approved upstream Python implementation for this run.

Do not modify any files, write any code, or change context. This task is validation only — a workflow safety gate.
