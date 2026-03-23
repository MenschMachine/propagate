You are reviewing changes that were automatically generated to propagate client SDK changes to the documentation project.

Inspect the current diff:

```bash
git diff main --stat
git diff main
```

Check for:

1. Do the provided code examples actually match the code in the client SDKs exactly?
2. Does the documentation cover all the new features and edge cases?
3. Are the provided code examples as simple as possible to showcase the new features?

Your job is to review the public documentation. Infrastructure, like GitHub Actions, is none of your business.

If there are issues, list each one clearly so the implementing agent can fix them. Be specific about file names and what needs to change. Store your findings:

```bash
propagate context set --stdin :review-findings <<'FINDINGS'
<your detailed findings>
FINDINGS
```

If everything looks good, do not write to `:review-findings`.
