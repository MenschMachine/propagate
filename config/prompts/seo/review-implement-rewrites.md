# Review Rewrite Implementation

You are reviewing edits to existing pages generated from rewrite briefs.

Inspect:

```bash
git diff main --stat
git diff main
```

Classify problems into two buckets:

- **Implementation problem**: the brief was sound, but the page edits are weak or wrong.
- **Brief problem**: the edits reveal that the brief itself is malformed, too abstract, or strategy-shaped.

Check:

- user value
- fit to page type
- natural public language
- section structure quality
- whether the page reads like website content instead of planning notes
- whether the page still feels like a template being filled in from the brief
- whether heading ideas and section choices feel specific to this page rather than reusable across any SDK/feature page

If the problem is in implementation:

```bash
propagate context set --stdin :review-findings <<'FINDINGS'
<blocking implementation findings>
FINDINGS
```

If the problem is in the brief:

```bash
propagate context set --stdin :review-findings-brief <<'FINDINGS'
<blocking brief findings>
FINDINGS
```

If there are only non-blocking improvements:

```bash
propagate context set --stdin :review-suggestions <<'SUGGESTIONS'
<non-blocking suggestions>
SUGGESTIONS
```

If the implementation is sound, write nothing.
