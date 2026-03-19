# Summarize Website Changes From Backend PR

Prepare the git metadata for the website changes you just made.

## Inputs

Read the relevant PRs again:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task implement-approved-api-docs-updates | xargs)"
API_DOCS_PR_NUMBER="$(propagate context get :api-docs-pr-number --task implement-approved-api-docs-updates | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,url
gh pr view "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs --json title,url
```

Inspect the current diff:

```bash
git status --short
git diff --stat
git diff
```

## Task

Set these context keys:

- `:website-commit-message`
- `:website-pr-body`

Requirements:

- The commit message subject should be: `website: reflect backend PR #<number>`
- Add a short body line or two if it helps explain the change.
- The PR body must be Markdown and include these sections:
  - `## Source Backend PR`
  - `## Source API Docs PR`
  - `## Implemented Changes`
  - `## Testing`
- In `## Source Backend PR`, include the backend PR URL.
- In `## Source API Docs PR`, include the api-docs PR URL.
- In `## Testing`, state what you actually ran. If you did not run tests, say so plainly.

Use `propagate context set` to store both values.
