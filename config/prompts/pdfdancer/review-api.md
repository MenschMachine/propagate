You are reviewing changes that were automatically generated to propagate a backend capability to the API.

Inspect the current diff:

```bash
git diff main --stat
git diff main
```

Check for:

- **Correctness** — does the implementation match what the capability describes?
- **Completeness** — are there missing pieces (routes, types, etc.)?
- **Style** — does it follow the existing codebase conventions?
- **Bugs** — any obvious issues, typos, or broken logic?

Especially check for:

- Sound and clear API design
- E2E tests for the new API exist, following the existing patterns. All e2e tests must have deep and precise assertions using the PDFAssertion class.
- Exceptions must never be swallowed.
- At least log level WARN must be used in case any problem occurs or things are not as they are supposed to be.
- API versioning rules are followed. Never introduce breaking changes in existing APIs.

Your job is to review the production and test code. Infrastructure, like GitHub Actions, is none of your business.

If there are issues, list each one clearly so the implementing agent can fix them. Be specific about file names and what needs to change. Store your findings:

```bash
propagate context set --stdin :review-findings <<'FINDINGS'
<your detailed findings>
FINDINGS
```

If everything looks good, do not write to `:review-findings`.
