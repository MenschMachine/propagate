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

Classify each finding into one of the following categories:

**BLOCKING** — issues in THIS repository that must be fixed:
- Incorrect behavior or logic bugs
- Missing required functionality (routes, types, test coverage for new code paths)
- Breaking API versioning rules
- Swallowed exceptions
- Tests with wrong or missing assertions

**NON-BLOCKING** — improvements in THIS repository that are nice-to-have:
- Naming or style inconsistencies
- Code that could be cleaner but works correctly
- Missing edge-case tests for pre-existing behavior

**UPSTREAM BUG** — a bug in `MenschMachine/pdfdancer-backend` that makes this API implementation incorrect. File a GitHub issue and store the URL:

```bash
ISSUE_URL=$(gh issue create --repo MenschMachine/pdfdancer-backend --title "<concise title>" --body "<description>")
propagate context set :upstream-bug "$ISSUE_URL"
```

**UPSTREAM IMPROVEMENT** — a suggestion for `MenschMachine/pdfdancer-backend` that does not affect correctness here. File a GitHub issue:

```bash
gh issue create --repo MenschMachine/pdfdancer-backend --title "<concise title>" --body "<description>"
```

Do not write to any review key for upstream improvements.

If there are BLOCKING issues, be specific about file names and what needs to change:

```bash
propagate context set --stdin :review-findings <<'FINDINGS'
<your blocking findings>
FINDINGS
```

If there are NON-BLOCKING suggestions:

```bash
propagate context set --stdin :review-suggestions <<'SUGGESTIONS'
<your non-blocking suggestions>
SUGGESTIONS
```

If everything looks good, do not write to any review key.
