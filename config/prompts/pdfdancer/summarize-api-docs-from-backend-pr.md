# Summarize API Docs Changes From Backend PR

Prepare the PR metadata for the api-docs changes you just made.

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

Write the final body to:

- `:api-docs-pr-body`

Requirements:

- The PR body must be Markdown and include these sections:
  - `## Source Backend PR`
  - `## Implemented Changes`
  - `## Testing`
  - `## Website Follow-Up`
- In `## Source Backend PR`, include the backend PR URL.
- In `## Testing`, state what you actually ran. If you did not run tests, say so plainly.
- In `## Website Follow-Up`, state that the website workflow will run after this PR is approved.

Important:

- Store `:api-docs-pr-body` in the execution-level context so the later `git:publish` step can read it.
- `propagate context set` already writes to execution scope by default in this workflow. Do not use `--local`.
- If you use a command, it should be equivalent to `propagate context set :api-docs-pr-body "<final body>"`.
