Prepare the PR body for this client SDK repository.

Read:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
API_PR_NUMBER="$(propagate context get :api-pr-number --task implement-pdfdancer-api | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,url
gh pr view "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json title,url
```

Write the final body to the repository-specific `*-pr-body` context key already configured for this execution.

Structure:

- `## Source Backend PR`
- `## Source API PR`
- short summary of the SDK changes
- `## Verification`
- `## Downstream Follow-Up` describing the examples stage
