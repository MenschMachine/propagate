# Summarize Rewrite Implementation PR

Run `git diff main` and summarize:

- which existing pages were revised
- how their structure or positioning changed
- any briefs that were intentionally only partially implemented

Save it:

```bash
propagate context set --stdin :implement-rewrites-summary <<'BODY'
<PR description>
BODY
```
