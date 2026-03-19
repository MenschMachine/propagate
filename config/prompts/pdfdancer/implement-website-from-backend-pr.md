# Implement Website Changes From Backend PR

This execution runs after the api-docs PR for the same backend PR is approved.

## Inputs

Read the source backend PR first:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task implement-approved-api-docs-updates | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
gh pr diff "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
```

Then read the approved `pdfdancer-api-docs` PR that landed for it:

```bash
API_DOCS_PR_NUMBER="$(propagate context get :api-docs-pr-number --task implement-approved-api-docs-updates | xargs)"
gh pr view "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs --json title,body,url,headRefName,baseRefName
gh pr diff "$API_DOCS_PR_NUMBER" --repo MenschMachine/pdfdancer-api-docs
```

If the repository has an `AGENTS.md` file, read it before editing anything.

## Task

Implement the dependent website changes in this repository.

Rules:

- Use the approved api-docs PR as the source of truth for what actually landed upstream.
- Use the backend PR to understand the underlying product behavior, terminology, and examples.
- Match the site's existing patterns and conventions.
- Keep changes scoped to the pages, navigation, examples, or explanatory content that should change because of the backend PR and the approved api-docs updates.
- Do not refactor unrelated code.
- Leave the git commit and PR creation to Propagate. Your job in this task is only the code change.
