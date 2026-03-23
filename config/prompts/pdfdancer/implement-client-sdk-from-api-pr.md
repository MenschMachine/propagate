Implement the client SDK work required by the authoritative upstream API changes.

Read:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
  gh pr diff "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
  API_PR_NUMBER="$(propagate context get :api-pr-number --task implement-pdfdancer-api | xargs)"
else
  API_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
fi
gh pr view "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json title,body,url,headRefName,baseRefName
gh pr diff "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api
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

- Implement the SDK support required by the approved upstream changes.
- Treat the approved API PR as the source of truth for the contract that actually landed.
- If this run started from a backend PR, use that backend PR to understand intent, terminology, and examples.
- Address the revision reason, check failures, and review comments before adding unrelated changes.
- Add or update e2e tests following the existing patterns. Tests should use `PDFAssertions` with deep, precise assertions; add helper methods there if needed.
- If tests expose a server-side bug, keep the failing test, stop, and write a detailed markdown bug report for the `pdfdancer-api` team instead of working around it.
- Do not make changes to GitHub workflow files.

## Starting the API Server

Use `${PROPAGATE_CONFIG_DIR}/scripts/start-api-server.sh` to get a running test server. It reuses an existing container if one is already running for this PR image.

```shell
API_BASE_URL="$("${PROPAGATE_CONFIG_DIR}/scripts/start-api-server.sh" "$API_PR_NUMBER")"
```

Swagger UI is available at `${API_BASE_URL}/swagger-ui`.
Use `PDFDANCER_API_TOKEN=42` when authenticating against the API.

## API Versioning and Page Indexing

- Always prefer the latest API version.
- API v0 uses 0-based page indexing.
- API v1 uses 1-based page indexing.

## Python SDK

- Always use a virtual environment.
