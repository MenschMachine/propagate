# Plan SEO Strategy

You are the strategy layer of the SEO pipeline.

Your job is to decide which opportunities from `:findings` should advance this run and which should be deferred. Do not
write implementation copy or editorial briefs here.

## Inputs

Read the findings from analyze:

```bash
propagate context get :findings --task analyze
```

Read prior review feedback if present:

```bash
propagate context get :review-findings || true
propagate context get :review-suggestions || true
propagate context get :revision-reason || true
```

Read prior PR feedback if present:

```bash
propagate context get :pr-comments || true
```

## Output responsibilities

Produce a strategy artifact at `reports/YYYY-MM-DD/strategy.md` that contains:

- the selected rewrite/technical items for this run
- the selected new-content items for this run
- explicit deferrals with reasons
- page type for each approved item
- the run-level implementation order

Keep strategy language internal. This file is for planning and review, not for implementation.

## Revision mode

If `:review-findings` exists, you are revising a previously rejected strategy. Address those findings first and make the
smallest coherent changes needed to resolve them.

If `:review-suggestions` exists without blocking findings, treat them as optional improvements. Incorporate them when
they clearly strengthen the strategy, but do not churn an otherwise sound plan just to satisfy every non-blocking note.

## Selection rules

- Select the strongest rewrite and technical opportunities that can plausibly be implemented well in one run.
- Select at most **3 substantial rewrite/technical items**.
- Select at most **2 new-content items**.
- Prefer coherent sets of pages over scattered low-leverage work.
- If a page is still in cool-down or lacks enough support in `:findings`, defer it.
- If the evidence supports a technical cleanup or ownership fix rather than a public page brief, classify it that way.
  Do not force a page-rewrite or new-content target when the underlying job is redirect cleanup, internal links,
  sitemap repair, canonical cleanup, or another technical change.
- If the right fix is to create a new destination, replace a redirect placeholder, or stand up a framework-specific or
  otherwise net-new page, classify it as `new-content`, not rewrite. Rewrite targets are for materially improving an
  existing destination that should continue to exist as that page.
- Every approved item must have a `page_type`:
  - `sdk-page`
  - `feature-page`
  - `industry-page`
  - `howto-page`
  - `hub-page`
  - `comparison-page`
  - `framework-page`

## Required context keys

Set these keys:

```bash
propagate context set :strategy-path "reports/YYYY-MM-DD/strategy.md"
```

```bash
propagate context set --stdin :rewrite-targets <<'JSON'
["/path-one/", "/path-two/"]
JSON
```

If there are any rewrite or technical targets, also set:

```bash
propagate context set :has-rewrite-targets true
```

If there are any new-content targets, also set:

```bash
propagate context set :has-new-content-targets true
```

```bash
propagate context set --stdin :new-content-targets <<'JSON'
["/path-three/"]
JSON
```

If and only if there are new-content targets and no rewrite targets, also set:

```bash
propagate context set :run-new-content-direct true
```

If there are no targets for a lane, write `[]` for that lane.
