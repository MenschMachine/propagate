Implement the `pdfdancer-api` changes required by the backend PR.

Read:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
gh pr diff "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
```

Always inspect prior revision context before making changes:

```bash
propagate context get :revision-reason || true
propagate context get :review-findings || true
propagate context get :review-check-results || true
propagate context get :pr-comments || true
```

The `:pr-comments` value is a JSON object with `comments` (issue-style) and `review_comments` (line-specific diff comments).

Requirements:

- Implement the API support implied by the backend PR in this repository.
- Use the backend PR as the source of truth for behavior and naming.
- Address the revision reason, failing checks, and review comments from prior iterations before making new changes.
- Keep changes scoped to the API work needed for the backend feature.
- Follow existing API patterns strictly and keep the exposed API as simple as possible.
- Add or update e2e tests following the existing patterns. Tests should use `PDFAssertion` with deep, precise assertions; add helper methods there if needed.
- If tests expose a backend bug, keep the failing test, stop, and write a detailed markdown bug report for the backend team instead of papering over the problem.
- Never swallow exceptions.
- Use at least log level `WARN` when things go wrong or the system is not in the expected state.

## API Versioning

- API v0 is legacy and should only receive bug fixes.
- API v1 is stable and should only receive non-breaking changes.
- Breaking changes require a new version such as v2.
