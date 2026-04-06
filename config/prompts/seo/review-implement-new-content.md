# Review New-Content Implementation

You are reviewing brand-new pages generated from editorial briefs.

Inspect:

```bash
git diff main --stat
git diff main
```

Classify problems into:

- **Implementation problem**: the brief was fine, but the new page is weak.
- **Brief problem**: the brief itself does not define a strong enough page.

Check:

- whether the page earns its existence
- whether it avoids duplicating nearby pages
- whether the page type is clear
- whether the public language is natural and specific

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
