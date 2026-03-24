Implement the `pdfdancer-www` changes required by the approved docs work.

Read:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  SOURCE_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
  gh pr diff "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
else
  SOURCE_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
  gh pr view "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json title,body,files,url,headRefName,baseRefName
  gh pr diff "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-api
fi
API_DOCS_PR_NUMBER="$(propagate context get :api-docs-pr-number --task implement-pdfdancer-api-docs | xargs)"
gh pr view "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs --json title,body,url,headRefName,baseRefName
gh pr diff "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs
```

Always inspect prior revision context before making changes:

```bash
propagate context get :revision-reason || true
propagate context get :review-findings || true
propagate context get :review-suggestions || true
propagate context get :review-check-results || true
propagate context get :pr-comments || true
```

The `:pr-comments` value is a JSON object with `comments` (issue-style) and `review_comments` (line-specific diff comments).

Use the approved docs PR as the source of truth for what landed upstream.
