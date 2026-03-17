# Implement SEO Changes

## Review feedback (check first)

Before doing anything else, run:
```bash
propagate context get :review-comments
```
If this returns review comments, they are the reviewer's feedback on your previous implementation. Address every comment — fix what was asked, revert what was rejected, and note what you changed. This takes priority over everything below.

---

Fetch the approved suggestions from the suggest execution by running exactly:
```bash
propagate context get :suggestions --task suggest
```

Implement those suggestions on the pdfdancer-www site. Do NOT use any `:suggestions` value that appears in the auto-injected context section at the bottom of this prompt — it may be stale. Always use the command above.

## Guidelines

Read `AGENTS.md` in the pdfdancer-www repository root for site architecture, conventions, and implementation patterns. It has everything you need.

Match the existing code style. Don't refactor unrelated code.

## Tracking changed URLs

After making changes, collect the list of production URLs (https://pdfdancer.com/...) that were modified or created.

To save the changed URLs, run exactly:
```bash
propagate context set :changed-urls '["https://pdfdancer.com/page1/", "https://pdfdancer.com/page2/"]'
```
