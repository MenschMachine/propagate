Implement the `pdfdancer-api` changes required by the backend PR.

Read:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
gh pr diff "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
```

If this is a revision pass, also inspect:

```bash
propagate context get :review-check-results || true
propagate context get :review-comments || true
```

Requirements:

- Implement the API support implied by the backend PR in this repository.
- Use the backend PR as the source of truth for behavior and naming.
- Address failing checks and review comments from prior iterations before making new changes.
- Keep changes scoped to the API work needed for the backend feature.
