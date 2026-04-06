# Summarize Implementation for PR

Run `git diff main` to see what changed. Write a clear PR description summarizing:
- Which approved briefs were implemented
- What files were changed and why
- Any approved items that were skipped and why

Save the summary to context:

```bash
propagate context set --stdin :implement-seo-summary <<'BODY'
<PR description>
BODY
```
