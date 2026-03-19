# Summarize Approved Website Suggestion Implementation

Prepare the git metadata for the changes you just made.

## Inputs

Read the issue again:

```bash
ISSUE_NUMBER="$(propagate context get :signal.issue_number | xargs)"
gh issue view "$ISSUE_NUMBER" --repo MenschMachine/pdfdancer-www --json title,body,url
API_DOCS_PR_NUMBER="$(propagate context get :api-docs-pr-number --task implement-approved-api-docs-updates | xargs)"
gh pr view "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs --json url
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

- The commit message subject should be: `website: implement approved suggestions from issue #<number>`
- Add a short body line or two if it helps explain the change.
- The PR body must be Markdown and include these sections:
  - `## Source Issue`
  - `## Source API Docs PR`
  - `## Implemented Changes`
  - `## Testing`
- In `## Source Issue`, include the issue URL.
- In `## Source API Docs PR`, include the api-docs PR URL.
- In `## Testing`, state what you actually ran. If you did not run tests, say so plainly.

Use `propagate context set` to store both values.
