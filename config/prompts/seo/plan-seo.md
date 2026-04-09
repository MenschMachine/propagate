# Plan SEO Strategy

You are the strategy layer of the SEO pipeline.

Your job is to decide which opportunities from `:findings` should advance this run, which should be deferred, and how
to brief the approved items well enough for one implementation execution to carry them out.

## Inputs

Read the findings from analyze:

```bash
propagate context get --global :findings
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
Do not split this into separate rewrite and new-page handoff files.

Each brief entry should at minimum include:

- `page.path`
- `page.change_type`
- `goal.primary_objective`
- `goal.target_audience`
- `goal.target_intent`
- `message.page_promise`
- `message.key_points_to_emphasize`
- `message.key_points_to_de_emphasize_or_remove`
- `product_truth.approved_claims`
- `product_truth.claims_to_avoid_or_verify`
- `implementation.must_change`
- `implementation.can_change`
- `implementation.must_keep`
- `success_criteria`
- `out_of_scope`

You may also include:

- `source_of_truth`

Use these `page.change_type` values only:

- `rewrite`
- `refresh`
- `expand`
- `trim`
- `new-page`

## Revision mode

If `:review-findings` exists, you are revising a previously rejected planning PR. Address those findings first and make
the smallest coherent changes needed to resolve them.

If `:review-suggestions` exists without blocking findings, treat them as optional improvements. Incorporate them when
they clearly strengthen the strategy, but do not churn an otherwise sound plan just to satisfy every non-blocking note.

## Selection rules

- Select the strongest opportunities that can plausibly be implemented well in one run.
- Select at most **4 substantial items total** across rewrites, refreshes, expansions, trims, and new pages.
- Prefer coherent sets of pages over scattered low-leverage work.
- If a page is still in cool-down or lacks enough support in `:findings`, defer it.
- Only approve public page work. If the evidence points to redirect cleanup, internal-link cleanup, sitemap repair,
  canonical cleanup, or another technical fix with no page brief to hand off, defer it instead of forcing it into this
  run.
- Use `new-page` when the right fix is to create a net-new destination. Use one of `rewrite`, `refresh`, `expand`, or
  `trim` when the job is to materially improve an existing page.
- Every approved item must point to one exact site path in `page.path`.
- Keep the brief practical and writable. Prioritize page intent, message direction, approved claims, change boundaries,
  and observable success criteria over internal SEO taxonomy or generic section templates.
- Include `source_of_truth` only when a link, doc, or internal note should resolve a likely claim conflict.

## Required context keys

Set these keys:

```bash
propagate context set --global :strategy-path "reports/YYYY-MM-DD/strategy.md"
```

```bash
propagate context set --global :implementation-briefs-path "reports/YYYY-MM-DD/implementation-briefs.yaml"
```

```bash
propagate context set --stdin --global :implementation-targets <<'JSON'
["/path-one/", "/path-two/", "/path-three/"]
JSON
```

If there are any approved implementation items, also set:

```bash
propagate context set --global :has-implementation-targets true
```

Save the brief artifact content too:

```bash
propagate context set --stdin --global :implementation-briefs <<'YAML'
- page:
    path: /path-one/
    change_type: rewrite
  goal:
    primary_objective: ...
    target_audience: ...
    target_intent: ...
  message:
    page_promise: ...
    key_points_to_emphasize:
      - ...
    key_points_to_de_emphasize_or_remove:
      - ...
  product_truth:
    approved_claims:
      - ...
    claims_to_avoid_or_verify:
      - ...
  implementation:
    must_change:
      - ...
    can_change:
      - ...
    must_keep:
      - ...
  out_of_scope:
    - ...
  success_criteria:
    - ...
  source_of_truth:
    - ...
YAML
```

If there are no approved implementation items, write `[]` for `:implementation-targets` and `[]` for
`:implementation-briefs`.
