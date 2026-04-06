# Summarize Rewrite Briefs PR

Run `git diff main` and summarize:

- how many rewrite briefs were added
- which page types are covered
- the strongest approved rewrite targets

Save it:

```bash
propagate context set --stdin :brief-rewrites-summary <<'BODY'
<PR description>
BODY
```
