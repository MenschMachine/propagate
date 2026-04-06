# Review New-Content Briefs

You are reviewing editorial briefs for brand-new pages.

Inspect the current diff:

```bash
git diff main --stat
git diff main
```

Check whether each brief:

- justifies why the page should exist separately
- defines a clear audience and page role
- avoids duplicating existing pages
- is written in editorial language rather than search-strategy language
- gives enough structure for a strong new page without forcing generic filler

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

If the briefs are sound, write nothing.
