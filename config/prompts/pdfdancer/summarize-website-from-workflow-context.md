Prepare the PR body for the `pdfdancer-www` changes.

Read:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
API_DOCS_PR_NUMBER="$(propagate context get :api-docs-pr-number --task implement-pdfdancer-api-docs | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,url
gh pr view "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs --json title,url
```

Store the final body using `propagate context set`:

```bash
propagate context set :website-pr-body "<final body>"
```

Structure:

- `## Source Backend PR`
- `## Source API Docs PR`
- short summary of website changes
- `## Verification`
