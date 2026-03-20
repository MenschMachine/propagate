This execution must continue from the approved TypeScript client PR for the same backend PR.

Validate:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
SDK_PR_NUMBER="$(propagate context get :client-typescript-pr-number --task implement-client-typescript | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,url,state,mergedAt
gh pr view "$SDK_PR_NUMBER" --repo MenschMachine/pdfdancer-client-typescript --json number,title,url,labels,state,headRefName,baseRefName
```

Fail fast unless both PRs exist and the SDK PR is the approved upstream TypeScript implementation for this backend PR.

Do not modify any files, write any code, or change context. This task is validation only — a workflow safety gate.
