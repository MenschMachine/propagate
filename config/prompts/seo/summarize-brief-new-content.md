# Summarize New-Content Briefs PR

Run `git diff main` and summarize:

- how many new-page briefs were added
- what kinds of pages they are
- why they were selected now

Save it:

```bash
propagate context set --stdin :brief-new-content-summary <<'BODY'
<PR description>
BODY
```
