# Summarize SEO Strategy PR

Run `git diff main` to inspect the planning artifacts.

Write a PR description that summarizes:

- how many implementation items were approved
- the mix of rewrite, refresh, expand, trim, and new-page work
- the top priorities
- the main defer reasons

Save it:

```bash
propagate context set --stdin :plan-seo-summary <<'BODY'
<PR description>
BODY
```
