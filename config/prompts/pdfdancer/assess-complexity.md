Assess the complexity of the downstream implementation work required by this workflow.

Inputs:

- `SOURCE_REPO="$(propagate context get --global :source-repository | xargs)"`
- `PR_NUMBER="$(propagate context get --global :source-pr-number | xargs)"`
- `gh pr diff "$PR_NUMBER" --repo "$SOURCE_REPO"`
- `gh pr view "$PR_NUMBER" --repo "$SOURCE_REPO" --json number,title,body,files,url`

IMPORTANT: The upstream PR size and complexity are irrelevant. A massive 100-file upstream PR can result in trivial downstream work. A tiny 1-file upstream PR can require complex downstream SDK design. Always assess what downstream must implement.

Tasks:

1. Read the upstream PR to understand what it changes.

2. Assess the downstream work required — the criteria below, applied to what downstream must implement.

3. Decision criteria — set **agent-hard** if ANY of:

   - The downstream work modifies existing client-facing API contracts or data models (not just adds new ones)
   - The downstream work modifies core business logic or introduces architectural changes in downstream repos
   - The downstream work is a refactor with non-trivial migration implications across repos
   - High risk of downstream regressions (security-sensitive, auth, behavioral changes clients depend on)

   Set **agent-easy** if ALL of:

   - The downstream work is a pure addition — new endpoints, new SDK methods, new features — that does NOT modify existing client-facing contracts
   - No coordinated cross-file changes needed in downstream (independent file additions are fine)
   - Low risk of regressions — the downstream is extended without altering existing behavior

4. Write the decision globally so all downstream executions use it:

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
