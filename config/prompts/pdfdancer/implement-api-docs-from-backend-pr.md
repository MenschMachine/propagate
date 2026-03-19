# Implement API Docs Changes From Backend PR

This execution starts directly from a labeled backend PR. There is no intermediate planning issue in this workflow.

## Inputs

Read the source backend PR first:

```bash
PR_NUMBER="$(propagate context get :source-backend-pr-number | xargs)"
gh pr view "$PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
gh pr diff "$PR_NUMBER" --repo MenschMachine/pdfdancer-backend
```

If the repository has an `AGENTS.md` file, read it before editing anything.

## Task

Implement the api-docs changes that the backend PR requires in this repository.

Rules:

- Use the backend PR as the source of truth for the product behavior, naming, and examples that must be documented.
- Match the repository's existing patterns and conventions.
- Keep changes scoped to the api-docs work implied by the backend PR.
- Update the most relevant docs, reference material, or examples rather than refactoring unrelated content.
- If the backend PR also implies website work, do not implement that here. The website repo runs after the api-docs PR is approved.
- Leave the git commit and PR creation to Propagate. Your job in this task is only the code change.
