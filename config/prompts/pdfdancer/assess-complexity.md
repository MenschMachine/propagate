Assess the complexity of the downstream implementation work required by this workflow.

Inputs:

- `SOURCE_REPO="$(propagate context get --global :source-repository | xargs)"`
- `PR_NUMBER="$(propagate context get --global :source-pr-number | xargs)"`
- `gh pr diff "$PR_NUMBER" --repo "$SOURCE_REPO"`
- `gh pr view "$PR_NUMBER" --repo "$SOURCE_REPO" --json number,title,body,files,url`

Tasks:

1. Read the upstream PR to understand what changed.

2. Assess the downstream work required. Consider:
   - For SDK implementations: how many SDKs need updating? Do the changes require new API surface, data model translations, or significant logic in each SDK?
   - For docs/examples: is the downstream documentation complex (new concepts, new API surfaces) or straightforward?
   - Is this a FULL pipeline (SDK + examples + docs) or DOCS-only?

3. Decision criteria — set **agent-hard** if ANY of:

   - The downstream implementation requires significant logic in multiple SDKs (not just passthrough calls)
   - The upstream change introduces new data models, API contracts, or wire formats that need careful handling across SDKs
   - The downstream work spans FULL pipeline (multiple SDKs + examples + docs) with non-trivial coordination
   - Despite being a small upstream PR, the downstream work is substantial (new concepts requiring careful SDK design)
   - High risk of downstream regressions if done hastily (e.g., security-sensitive, auth changes)

   Set **agent-easy** if ALL of:

   - The downstream work is straightforward: adding new endpoints, new SDK methods, or new features that slot into existing patterns
   - Each SDK change is independent and follows existing patterns (no new abstractions needed)
   - DOCS-only pipeline or the new surface area is simple to document
   - Low risk — the change is additive and doesn't alter existing behavior clients depend on

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
