# Implement New-Content Briefs

You are creating brand-new user-facing pages on `pdfdancer.com`.

Read the approved new-content briefs:

```bash
propagate context get :new-content-briefs --task brief-new-content
```

If a refined local brief exists from a prior review pass, use it instead:

```bash
propagate context get :active-new-content-briefs
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

Prefer `:active-new-content-briefs` when present; otherwise use the approved briefs from `brief-new-content`.

If prior review findings exist, resolve them directly instead of reinterpreting the page from scratch.

For each new page:

1. Identify the page type and nearby existing pages.
2. Draft an internal outline first.
3. Make the page distinct from nearby pages in role and substance.
4. Write public copy that feels native to the site rather than SEO-generated.

## Deliverables

- Create the approved new pages.
- Track every changed production URL.

Save changed URLs:

```bash
propagate context set --stdin :changed-urls-new-content <<'URLS'
["https://pdfdancer.com/page-new/"]
URLS
```
