Implement the client SDK work required by the authoritative upstream API changes.

Read:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
  gh pr diff "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
  API_PR_NUMBER="$(propagate context get :api-pr-number --task implement-pdfdancer-api | xargs)"
else
  API_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
fi
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
- If this run started from a backend PR, use that backend PR to understand intent, terminology, and examples.
- Address check failures and review comments before adding unrelated changes.
