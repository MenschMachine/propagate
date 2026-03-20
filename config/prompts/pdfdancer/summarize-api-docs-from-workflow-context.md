Prepare the PR body for the `pdfdancer-api-docs` changes.

Read the source PR, and if present also the upstream API/examples PR URLs.

Write the final body to:

- `:api-docs-pr-body`

Important:

- Store `:api-docs-pr-body` in the execution-level context so the later `git:publish` step can read it.
- `propagate context set` already writes to execution scope by default in this workflow. Do not use `--local`.
- If you use a command, it should be equivalent to:

```bash
propagate context set :api-docs-pr-body "<final body>"
```

Structure:

- `## Source Upstream PR`
- `## Upstream Inputs`
- short summary of docs changes
- `## Verification`
- `## Website Follow-Up`
