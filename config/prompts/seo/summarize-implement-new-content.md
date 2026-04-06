# Summarize New-Content Implementation PR

Run `git diff main` and summarize:

- which new pages were created
- what visitor/job each page serves
- any intentionally deferred related pages

Save it:

```bash
propagate context set --stdin :implement-new-content-summary <<'BODY'
<PR description>
BODY
```
