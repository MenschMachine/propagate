# Implement SEO Changes

Read `:suggestions` from context. Implement the approved suggestions on the pdfdancer-www site.

If there are PR comments from a previous review (visible in context), address that feedback and revise your implementation.

## Guidelines

Read `AGENTS.md` in the pdfdancer-www repository root for site architecture, conventions, and implementation patterns. It has everything you need.

Match the existing code style. Don't refactor unrelated code.

## Tracking changed URLs

After making changes, collect the list of production URLs (https://pdfdancer.com/...) that were modified or created.

To read the suggestions from the suggest execution, run exactly:
```bash
propagate context get :suggestions --task suggest
```

To save the changed URLs, run exactly:
```bash
propagate context set :changed-urls '["https://pdfdancer.com/page1/", "https://pdfdancer.com/page2/"]'
```
