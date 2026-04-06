# Review SEO Strategy

You are reviewing the run-level SEO planning PR before implementation begins.

Inspect the current diff:

```bash
git diff main --stat
git diff main
```

Check:

- whether the selected items are actually supported by `:findings`
- whether the run is focused enough to implement well
- whether page types and `change_type` values are assigned sensibly
- whether deferrals make sense
- whether the strategy over-relies on internal SEO taxonomy instead of page/job reality
- whether the implementation briefs are actually writable
- whether the briefs center page promise, reader questions, proof, and constraints instead of generic section templates
- whether the planning PR would let one implementation execution carry the whole approved set without further
  orchestration

Classify findings as:

- **BLOCKING**: strategy must change before briefing
- **NON-BLOCKING**: sensible tweaks, ordering, or prioritization improvements

If there are BLOCKING issues:

```bash
propagate context set --stdin :review-findings <<'FINDINGS'
<your blocking findings>
FINDINGS
```

If there are NON-BLOCKING suggestions:

```bash
propagate context set --stdin :review-suggestions <<'SUGGESTIONS'
<your non-blocking suggestions>
SUGGESTIONS
```

If the strategy is sound, write nothing.
