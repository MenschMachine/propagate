Implement the `pdfdancer-api-docs` changes required by this backend workflow.

Read:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
gh pr diff "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
propagate context get :api-pr-number --task implement-pdfdancer-api || true
propagate context get :client-typescript-examples-pr-number --task implement-client-typescript-examples || true
propagate context get :client-python-examples-pr-number --task implement-client-python-examples || true
propagate context get :client-java-examples-pr-number --task implement-client-java-examples || true
```

If those upstream PR numbers exist, treat the approved upstream PRs as the source of truth for what landed. If they do not exist, this is the docs-only branch and the backend PR is the only source of truth.

If revising, also inspect `:review-check-results` and `:review-comments`.
