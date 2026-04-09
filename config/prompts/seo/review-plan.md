# Review SEO Strategy

You are reviewing the run-level SEO planning PR before implementation begins.

Inspect the current diff:

```bash
git diff main --stat
git diff main
```

Read the current findings before judging the strategy:

```bash
propagate context get --global :findings
```

Check:

- whether the selected items are actually supported by `:findings`
- whether the run is focused enough to implement well
- whether `page.path` and `page.change_type` are assigned sensibly
- whether deferrals make sense
- whether the strategy over-relies on internal SEO taxonomy instead of page/job reality
- whether the implementation briefs are actually writable
- whether the briefs separate approved claims from claims to avoid or verify
- whether `must_change`, `can_change`, and `must_keep` create clear editing boundaries
- whether the success criteria are concrete and observable in final page copy
- whether the briefs center page promise, audience, intent, and message priorities instead of generic section templates
- whether the planning PR would let one implementation execution carry the whole approved set without further
  orchestration

Do not write vague review comments. Every finding must point to a concrete problem in the current plan and explain what
must change.

Classify findings as:

- **BLOCKING**: strategy must change before briefing
- **NON-BLOCKING**: sensible tweaks, ordering, or prioritization improvements

Use this format for each BLOCKING finding:

```markdown
- Brief field or section: `<path, heading, or YAML field>`
  Problem: `<what is wrong or too abstract>`
  Why this blocks implementation: `<why implement-seo could not act on it reliably>`
  Required fix: `<specific change needed>`
```

Use this format for each NON-BLOCKING suggestion:

```markdown
- Brief field or section: `<path, heading, or YAML field>`
  Suggestion: `<specific improvement>`
  Why it helps: `<one sentence>`
```

Prefer blocking findings when a brief:
- cannot be tied back to a supported finding in `:findings`
- asks for a page change without a clear `page.path`
- uses `must_change` or `must_keep` language that is too vague to act on
- leaves claim safety ambiguous between `approved_claims` and `claims_to_avoid_or_verify`
- sets success criteria that are not observable in final copy

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
