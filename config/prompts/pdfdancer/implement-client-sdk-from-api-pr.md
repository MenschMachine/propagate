Implement the client SDK work required by the backend PR and the approved API PR.

Read:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
API_PR_NUMBER="$(propagate context get :api-pr-number --task implement-pdfdancer-api | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
gh pr diff "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
gh pr view "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json title,body,url,headRefName,baseRefName
gh pr diff "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api
```

If this is a revision pass, also inspect:

```bash
propagate context get :review-check-results || true
propagate context get :review-comments || true
```

Requirements:

- Implement the SDK support required by the approved upstream changes.
- Treat the approved API PR as the source of truth for the contract that actually landed.
- Use the backend PR to understand intent, terminology, and examples.
- Address check failures and review comments before adding unrelated changes.
