# Review Rewrite Briefs

You are reviewing editorial briefs for existing-page rewrites.

Inspect the current diff:

```bash
git diff main --stat
git diff main
```

Check whether the briefs are actually writable:

- do they define a clear page role?
- do they define the intended visitor in editorial language?
- do they specify structure and substance instead of abstract strategy?
- do they avoid internal taxonomy and planning language?
- do they leave no important decisions to the implementer?

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
