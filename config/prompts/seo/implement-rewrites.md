# Implement Rewrite Briefs

You are editing existing user-facing pages on `pdfdancer.com`.

Read the approved rewrite briefs:

```bash
propagate context get :rewrite-briefs --task brief-rewrites
```

If a refined local brief exists from a prior review pass, use it instead:

```bash
propagate context get :active-rewrite-briefs
```

Read prior review feedback if present:

```bash
propagate context get :review-findings || true
propagate context get :review-suggestions || true
propagate context get :revision-reason || true
propagate context get :pr-comments || true
```

Read `AGENTS.md` in the site root before making changes.

## Working method

Prefer `:active-rewrite-briefs` when present; otherwise use the approved briefs from `brief-rewrites`.

If prior review findings exist, resolve them directly instead of reinterpreting the whole brief from scratch.

For each target page:

1. Inspect the existing page and summarize its current section structure for yourself.
2. Build a revised outline that satisfies the brief.
3. Map each major section to keep, rewrite, remove, or add.
4. Make the minimum coherent edits needed to turn the page into the intended version.

SEO is input, not public voice. Write natural website content for real visitors.

## Deliverables

- Implement the approved rewrite briefs.
- Track every changed production URL.

Save changed URLs:

```bash
propagate context set --stdin :changed-urls-rewrites <<'URLS'
["https://pdfdancer.com/page1/"]
URLS
```
