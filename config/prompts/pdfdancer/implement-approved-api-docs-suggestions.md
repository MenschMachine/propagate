# Implement Approved API Docs Suggestions

This execution runs first after the planning issue in `pdfdancer-www` is labeled `approved`.

## Inputs

Read the approved issue first:

```bash
ISSUE_NUMBER="$(propagate context get :signal.issue_number | xargs)"
gh issue view "$ISSUE_NUMBER" --repo MenschMachine/pdfdancer-www --json title,body,url,labels
```

If the repository has an `AGENTS.md` file, read it before editing anything.

## Task

Implement the `## Recommended API Docs Changes` section from the approved planning issue in this repository.

Rules:

- Match the repository's existing patterns and conventions.
- Do not refactor unrelated code.
- Keep changes scoped to the api-docs work implied by the approved issue.
- If the issue also contains website work, do not implement that here. The website repo runs later.
- Leave the git commit and PR creation to Propagate. Your job in this task is only the code change.
