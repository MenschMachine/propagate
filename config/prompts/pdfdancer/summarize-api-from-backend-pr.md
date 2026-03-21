Prepare the PR body for the `pdfdancer-api` changes.

Read:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,url
```

Write the final body by running this exact command:

```bash
propagate context set :api-pr-body "<your PR body here>"
```

Structure:

- `## Source Backend PR`
- short summary of what changed in `pdfdancer-api`
- `## Verification`
- `## Downstream Follow-Up` describing the client SDK stage
