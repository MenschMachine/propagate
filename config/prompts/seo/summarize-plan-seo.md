# Summarize SEO Strategy PR

Run `git diff main` to inspect the strategy artifact.

Write a PR description that summarizes:

- how many rewrite/technical items were approved
- how many new-content items were approved
- the top priorities
- the main defer reasons

Save it:

```bash
propagate context set --stdin :plan-seo-summary <<'BODY'
<PR description>
BODY
```
