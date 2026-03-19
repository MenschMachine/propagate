Prepare the PR body for the `pdfdancer-api` changes.

Read:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,url
```

Write the final body to:

- `:api-pr-body`

Important:

- Store `:api-pr-body` in the execution-level context so the later `git:publish` step can read it.
- `propagate context set` already writes to execution scope by default in this workflow. Do not use `--local`.
- If you use a command, it should be equivalent to `propagate context set :api-pr-body "<final body>"`.

Structure:

- `## Source Backend PR`
- short summary of what changed in `pdfdancer-api`
- `## Verification`
- `## Downstream Follow-Up` describing the client SDK stage
