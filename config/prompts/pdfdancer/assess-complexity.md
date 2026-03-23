Assess the complexity of the upstream change that triggered this workflow.

Inputs:

- `SOURCE_REPO="$(propagate context get --global :source-repository | xargs)"`
- `PR_NUMBER="$(propagate context get --global :source-pr-number | xargs)"`
- `gh pr diff "$PR_NUMBER" --repo "$SOURCE_REPO"`
- `gh pr view "$PR_NUMBER" --repo "$SOURCE_REPO" --json number,title,body,files,url`

Tasks:

1. Analyze the diff to judge complexity:

   - Count total lines changed (additions + deletions)
   - Count number of files modified
   - Identify whether the change affects API contracts, data models, or core logic
   - Assess risk level and potential for regressions

2. Decision criteria:

   - **agent-easy** if ALL of:
     - Small diff (under 200 lines total)
     - Few files changed (under 5)
     - No changes to core API contracts or data models
     - Pure documentation, configuration, or cosmetic changes
     - Low risk of regressions

   - **agent-hard** if ANY of:
     - Large diff (200+ lines) or many files (5+)
     - Changes to API contracts, data models, or core business logic
     - New features or significant functionality changes
     - Complex refactoring or multi-file coordinated changes
     - High risk of regressions or backward compatibility concerns

3. Write the decision globally so all downstream executions use it:

```bash
propagate context set --global :agent agent-easy
```

or

```bash
propagate context set --global :agent agent-hard
```

Also save a short rationale for traceability:

```bash
propagate context set --global :complexity-reason "<easy or hard>: <one-sentence reason>"
```

Be decisive. Set only one agent.
