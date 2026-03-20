This execution must continue from the approved `pdfdancer-api-docs` PR for the same source PR.

Validate:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  SOURCE_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,url,state,mergedAt
else
  SOURCE_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
  gh pr view "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json number,title,url,state,mergedAt
fi
API_DOCS_PR_NUMBER="$(propagate context get :api-docs-pr-number --task implement-pdfdancer-api-docs | xargs)"
gh pr view "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs --json number,title,url,labels,state,headRefName,baseRefName
```

Fail fast unless the source PR exists and is merged and the api-docs PR is the approved upstream docs implementation.

Do not modify any files, write any code, or change context. This task is validation only — a workflow safety gate.
