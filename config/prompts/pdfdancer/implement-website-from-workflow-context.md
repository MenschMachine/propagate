Implement the `pdfdancer-www` changes required by the approved docs work.

Read:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
API_DOCS_PR_NUMBER="$(propagate context get :api-docs-pr-number --task implement-pdfdancer-api-docs | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
gh pr diff "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
gh pr view "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs --json title,body,url,headRefName,baseRefName
gh pr diff "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs
```

If revising, also inspect `:review-check-results` and `:review-comments`.

Use the approved docs PR as the source of truth for what landed upstream.
