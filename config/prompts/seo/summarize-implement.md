# Summarize Implementation for PR

Run `git diff main` to see what changed. Write a clear PR description summarizing:
- Which suggestions were implemented
- What files were changed and why
- Any suggestions that were skipped and why

Save the summary to context:

```bash
propagate context set --stdin :implement-summary <<'BODY'
<PR description>
BODY
```
