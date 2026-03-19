# Implement Approved Website Suggestions

This execution runs only after a validation task confirms the approved issue is a generated website-suggestions planning issue.

## Inputs

Read the approved issue first:

```bash
ISSUE_NUMBER="$(propagate context get :signal.issue_number | xargs)"
gh issue view "$ISSUE_NUMBER" --repo MenschMachine/pdfdancer-www --json title,body,url,labels
```

Then read the approved `pdfdancer-api-docs` PR that this step depends on:

```bash
API_DOCS_PR_NUMBER="$(propagate context get :api-docs-pr-number --task implement-approved-api-docs-updates | xargs)"
gh pr view "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs --json title,body,url,headRefName,baseRefName
gh pr diff "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs
```

If the repository has an `AGENTS.md` file, read it before editing anything.

## Task

Implement the approved suggestions from the issue in this repository.

Rules:

- Match the site's existing patterns and conventions.
- Do not refactor unrelated code.
- Keep changes scoped to what the approved issue requests and what the approved api-docs PR actually changed.
- The issue's `## Recommended Website Changes` section is your primary implementation scope.
- Treat the issue body as structured workflow input: it should already contain a source PR backlink and concrete website suggestions.
- Use the api-docs PR as the source of truth for what landed upstream before you update the website.
- If the issue contains multiple suggestions, implement the ones that are clearly approved and technically actionable.
- Leave the git commit and PR creation to Propagate. Your job in this task is only the code change.
