# Plan SEO Strategy

You are the strategy layer of the SEO pipeline.

Your job is to decide which opportunities from `:findings` should advance this run, which should be deferred, and how
to brief the approved items well enough for one implementation execution to carry them out.

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

Produce two artifacts:

- `reports/YYYY-MM-DD/strategy.md`
- `reports/YYYY-MM-DD/implementation-briefs.yaml`

`strategy.md` should contain:

- the approved items for this run
- explicit deferrals with reasons
- the run-level implementation order
- internal planning rationale

`implementation-briefs.yaml` should contain the typed implementation briefs for every approved item in this run.
This is the only handoff artifact that `implement-seo` should need.
Do not split this into separate rewrite and new-content handoff files.

Each brief entry should at minimum include:

- `target`
- `change_type`
- `page_type`
- `priority`
- `primary_audience`
- `visitor_state`
- `page_role`
- `page_promise`
- `core_reader_questions`
- `proof_points`
- `constraints`
- `out_of_scope`
- `acceptance_criteria`

## Revision mode

If `:review-findings` exists, you are revising a previously rejected planning PR. Address those findings first and make
the smallest coherent changes needed to resolve them.

If `:review-suggestions` exists without blocking findings, treat them as optional improvements. Incorporate them when
they clearly strengthen the strategy, but do not churn an otherwise sound plan just to satisfy every non-blocking note.

## Selection rules

- Select the strongest opportunities that can plausibly be implemented well in one run.
- Select at most **4 substantial items total** across rewrites, new pages, and technical changes.
- Prefer coherent sets of pages over scattered low-leverage work.
- If a page is still in cool-down or lacks enough support in `:findings`, defer it.
- If the evidence supports a technical cleanup or ownership fix rather than a public page brief, classify it that way.
  Do not force a page-rewrite or new-content target when the underlying job is redirect cleanup, internal links,
  sitemap repair, canonical cleanup, or another technical change.
- If the right fix is to create a new destination, replace a redirect placeholder, or stand up a framework-specific or
  otherwise net-new page, classify it as `new-content`. If the right fix is to materially improve an existing
  destination, classify it as `rewrite`. Keep that distinction inside the brief `change_type`, but do not split this
  into separate rewrite and new-content handoff files.
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
propagate context set :implementation-briefs-path "reports/YYYY-MM-DD/implementation-briefs.yaml"
```

```bash
propagate context set --stdin :implementation-targets <<'JSON'
["/path-one/", "/path-two/", "/path-three/"]
JSON
```

If there are any approved implementation items, also set:

```bash
propagate context set :has-implementation-targets true
```

Save the brief artifact content too:

```bash
propagate context set --stdin :implementation-briefs <<'YAML'
- target: /path-one/
  change_type: rewrite
  page_type: sdk-page
  priority: high
  primary_audience: ...
  visitor_state: ...
  page_role: ...
  page_promise: ...
  core_reader_questions:
    - ...
  proof_points:
    - ...
  constraints:
    - ...
  out_of_scope:
    - ...
  acceptance_criteria:
    - ...
YAML
```

If there are no approved implementation items, write `[]` for `:implementation-targets` and `[]` for
`:implementation-briefs`.
