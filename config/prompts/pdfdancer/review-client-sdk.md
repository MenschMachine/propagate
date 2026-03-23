You are reviewing changes that were automatically generated to propagate an API capability to the client SDK.

Inspect the current diff:

```bash
git diff main --stat
git diff main
```

Check for:

- **Correctness** — does the implementation match what the capability describes?
- **Completeness** — are there missing pieces? Error cases not handled, features or parameters not implemented? Execution paths not covered by tests?
- **Style** — does it follow the existing codebase conventions?
- **Bugs** — any obvious issues, typos, or broken logic?

Especially check for:

- Sound and clear API design
- E2E tests for the new API exist, following the existing patterns. All e2e tests must have deep and precise assertions using the PDFAssertion class.

 Assume new files in the diff are intentional unless they are clearly local-only environment files, caches, or build artifacts.

Your job is to review the production and test code. Infrastructure, like GitHub Actions, is none of your business.

API versioning: always prefer the latest version of the API. API v0 uses 0-based page indexing. API v1 uses 1-based page indexing.

If there are issues, list each one clearly so the implementing agent can fix them. Be specific about file names and what needs to change. Store your findings:

```bash
propagate context set --stdin :review-findings <<'FINDINGS'
<your detailed findings>
FINDINGS
```

If everything looks good, do not write to `:review-findings`.
