# Summarize Suggestions for PR

Run `git diff main` to see what changed. Write a clear PR description summarizing:
- How many suggestions by type (meta, content-edit, new-content, technical)
- The highest priority items
- Data highlights that motivated the suggestions

Save the summary to context:

```bash
propagate context set --stdin :summary <<'BODY'
<PR description>
BODY
```
