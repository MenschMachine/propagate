Assess the complexity of the upstream change that triggered this workflow.

Inputs:

- `SOURCE_REPO="$(propagate context get --global :source-repository | xargs)"`
- `PR_NUMBER="$(propagate context get --global :source-pr-number | xargs)"`
- `gh pr diff "$PR_NUMBER" --repo "$SOURCE_REPO"`
- `gh pr view "$PR_NUMBER" --repo "$SOURCE_REPO" --json number,title,body,files,url`

Tasks:

1. Analyze the diff to judge what kind of change it is:

   - Is this a **core** change (touches data models, API contracts, core business logic, or requires multi-file coordination)?
   - Or is this an **on-top** addition (slots into an existing API, adds new endpoints/methods without changing existing contracts)?

2. Decision criteria — set **agent-hard** if ANY of:

   - The change modifies data models, API schemas, or wire formats consumed by clients
   - The change touches core business logic or introduces architectural changes
   - The change requires coordinated updates across 3+ files for correctness
   - The change is a refactor with non-trivial migration implications
   - Despite being small, the change is high-risk (e.g., security-sensitive, auth, data handling)

   Set **agent-easy** if ALL of:

   - The change is a pure addition — new endpoints, new SDK methods, new features — that do NOT modify existing contracts
   - No coordinated cross-file changes needed (a few independent file additions are fine)
   - Low risk of regressions — the existing system is not modified, only extended

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
