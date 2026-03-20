Prepare the PR body for the `pdfdancer-api-docs` changes.

Read the source PR, and if present also the upstream API/examples PR URLs.

Store the final body using `propagate context set`:

```bash
propagate context set :api-docs-pr-body "<final body>"
```

Structure:

- `## Source Upstream PR`
- `## Upstream Inputs`
- short summary of docs changes
- `## Verification`
- `## Website Follow-Up`
