Implement the TypeScript examples changes required by the approved upstream work.

Read:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
  gh pr diff "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
else
  API_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
  gh pr view "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json title,body,files,url,headRefName,baseRefName
  gh pr diff "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api
fi
SDK_PR_NUMBER="$(propagate context get :client-typescript-pr-number --task implement-client-typescript | xargs)"
gh pr view "$SDK_PR_NUMBER" --repo MenschMachine/pdfdancer-client-typescript --json title,body,url,headRefName,baseRefName
gh pr diff "$SDK_PR_NUMBER" --repo MenschMachine/pdfdancer-client-typescript
```

If revising, also inspect `:review-check-results` and `:review-comments`.

Keep changes scoped to TypeScript examples or sample applications that must reflect the approved client changes.
