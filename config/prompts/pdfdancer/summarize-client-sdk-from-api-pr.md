Prepare the PR body for this client SDK repository.

Read:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,url
  API_PR_NUMBER="$(propagate context get :api-pr-number --task implement-pdfdancer-api | xargs)"
else
  API_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
fi
gh pr view "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json title,url
```

Write the final body to the repository-specific `*-pr-body` context key already configured for this execution.

Structure:

- `## Source API PR`
- If the run started from a backend merge, also include `## Source Backend PR`
- short summary of the SDK changes
- `## Verification`
- `## Downstream Follow-Up` describing the examples stage
