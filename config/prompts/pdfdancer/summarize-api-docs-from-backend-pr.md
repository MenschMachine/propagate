# Summarize API Docs Changes From Backend PR

Prepare the git metadata for the api-docs changes you just made.

## Inputs

Read the source backend PR again:

```bash
PR_NUMBER="$(propagate context get :source-backend-pr-number | xargs)"
gh pr view "$PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,url
```

Inspect the current diff:

```bash
git status --short
git diff --stat
git diff
```

## Task

Set these context keys:

- `:api-docs-commit-message`
- `:api-docs-pr-body`

Requirements:

- The commit message subject should be: `api-docs: document backend PR #<number>`
- Add a short body line or two if it helps explain the change.
- The PR body must be Markdown and include these sections:
  - `## Source Backend PR`
  - `## Implemented Changes`
  - `## Testing`
  - `## Website Follow-Up`
- In `## Source Backend PR`, include the backend PR URL.
- In `## Testing`, state what you actually ran. If you did not run tests, say so plainly.
- In `## Website Follow-Up`, state that the website workflow will run after this PR is approved.

Use `propagate context set` to store both values.
