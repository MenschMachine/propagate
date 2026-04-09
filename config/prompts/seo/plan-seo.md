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
- the exact finding reference or evidence summary behind each approved item

`implementation-briefs.yaml` should contain the typed implementation briefs for every approved item in this run.
This is the only handoff artifact that `implement-seo` should need.
Do not split this into separate rewrite and new-page handoff files.

The plan step must make the approval logic auditable. For every approved item, show exactly which finding from
`:findings` supports it. Do not approve an item on general SEO intuition alone.

Each brief entry should at minimum include:

- `page.path`
- `page.change_type`
- `evidence.summary`
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

`evidence.summary` must be a short, concrete restatement of the supporting finding. Include the page or query, the core
diagnosis, and the reason this item should advance now. Do not paste the whole analysis report.

## Revision mode

If `:review-findings` exists, you are revising a previously rejected planning PR. Address those findings first and make
the smallest coherent changes needed to resolve them.

In revision mode, make an explicit pass over every blocking finding before you finalize the new plan.

For each blocking finding, either:

- change the strategy or briefs so the finding is no longer true, or
- remove the affected item from the approved set and defer it with a concrete reason in `strategy.md`

Do not keep an approved item in the run if its brief still depends on vague proof language, unsupported claims,
subjective success criteria, or any other condition the reviewer said makes it non-writable.

When a prior finding says the briefs are too abstract or not safely writable, prefer narrowing the approved set and
tightening the brief over producing another broad rewrite of the same idea.

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
- Every approved item must cite one concrete supporting finding in `evidence.summary`.
- If you cannot point to a specific finding with enough evidence, defer the item instead of inventing a brief.
- Keep the brief practical and writable. Prioritize page intent, message direction, approved claims, change boundaries,
  and observable success criteria over internal SEO taxonomy or generic section templates.
- Include `source_of_truth` only when a link, doc, or internal note should resolve a likely claim conflict.

## Working method

Work in this order:

1. Read `:findings` and list the candidate items that are actually supportable.
2. Defer anything blocked by weak evidence, cool-down status, or lack of a clear public page action.
3. Pick the strongest coherent set for this run.
4. For each approved item, write `evidence.summary` before you write the rest of the brief.
5. Write the brief only after the evidence, path, and change type are clear.

Do not let the brief become the reasoning. The finding comes first; the brief is the handoff built from it.

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
  evidence:
    summary: Page `/path-one/` has high impressions, low CTR, and a multi-week decline against the target query set.
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
