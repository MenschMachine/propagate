# Implement SEO Changes

## Review feedback (check first)

Before doing anything else, run:
```bash
propagate context get :pr-comments
```
This returns a JSON object with two keys:
- `comments`: issue-style PR comments (general feedback on the PR)
- `review_comments`: line-specific diff comments (reviewer feedback on specific lines)

If there are review_comments, they are the reviewer's feedback on your previous implementation. Address every comment — fix what was asked, revert what was rejected, and note what you changed. This takes priority over everything below.

---

Fetch the approved suggestions by running exactly:
```bash
propagate context get :suggestions --task suggest
```

Implement those suggestions on the pdfdancer-www site.

## Guidelines

Read `AGENTS.md` in the pdfdancer-www repository root for site architecture, conventions, and implementation patterns. It has everything you need.

Match the existing code style. Don't refactor unrelated code.

## Tracking changed URLs

After making changes, collect the list of production URLs (https://pdfdancer.com/...) that were modified or created.

To save the changed URLs, run exactly:
```bash
propagate context set --stdin :changed-urls <<'URLS'
["https://pdfdancer.com/page1/", "https://pdfdancer.com/page2/"]
URLS
```
