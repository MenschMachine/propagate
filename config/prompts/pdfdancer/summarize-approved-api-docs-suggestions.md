# Summarize Approved API Docs Suggestion Implementation

Prepare the git metadata for the api-docs changes you just made.

## Inputs

Read the issue again:

```bash
ISSUE_NUMBER="$(propagate context get :signal.issue_number | xargs)"
gh issue view "$ISSUE_NUMBER" --repo MenschMachine/pdfdancer-www --json title,body,url
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

- The commit message subject should be: `api-docs: implement approved suggestions from issue #<number>`
- Add a short body line or two if it helps explain the change.
- The PR body must be Markdown and include these sections:
  - `## Source Issue`
  - `## Implemented Changes`
  - `## Testing`
- In `## Source Issue`, include the issue URL.
- In `## Testing`, state what you actually ran. If you did not run tests, say so plainly.
- Mention that website follow-up will run after this PR is approved.

Use `propagate context set` to store both values.
