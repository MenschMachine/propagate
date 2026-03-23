Prepare the PR body for the `pdfdancer-api-docs` changes.

Read the source PR, and if present also the upstream API/examples PR URLs.

Run this exact command to store the PR body:

```bash
propagate context set --stdin :api-docs-pr-body <<'BODY'
<your PR body here>
BODY
```

Structure:

- `## Source Upstream PR`
- `## Upstream Inputs`
- short summary of docs changes
- `## Verification`
- `## Website Follow-Up`
