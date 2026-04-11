# Analyze SEO Data

Process Google Search Console (GSC) and PostHog data to identify actionable SEO opportunities **and implementation follow-ups**. Use current data plus prior SEO implementation history to produce a concise report for `plan-seo`.

## Inputs

Read required context:

```bash
propagate context get --global :gsc-data-path
propagate context get --global :posthog-data-path
propagate context get --global :intent-match
```

Also inspect page JSONs from `data/*/pages/*.json` and the newest enrichment directory under `data/enrichment/`.

## Analysis Rules

### Core opportunity signals

- Low CTR: impressions ≥ 50 and CTR < 3%
- Position drop: impressions > 20 and clear rank decline
- Striking distance: position 4–20
- Intent mismatch: queries land on the wrong page
- Technical/indexing: zero clicks despite impressions, or indexing/deployment evidence suggests the change is not live

### Trend and engagement labels

- Trend: `Declining`, `Stable`, `Improving`, or `New`
- Engagement: `content-problem` (>70% bounce), `content-weak` (50–70%), `content-delivers` (<40%), `low-confidence` (<5 pageviews), or `n/a`

### Diagnosis rules

- Use intent-match data to prefer `intent-mismatch` over a weaker `meta` diagnosis when intent clearly disagrees.
- For `meta` findings, always include the current indexed `title` and `meta_description`.
- For thin content, flag missing H1 or roughly <500 words as `content-depth` or `content-quality`, whichever better fits the evidence.
- Use `deployment_status` from `:evaluation-results`:
  - `not_yet_indexed` => valid `technical` finding
  - `confirmed_indexed` => do not claim an indexing problem
  - `unknown` => do not assert indexing as the diagnosis

## SEO Implementation History (Required):

Read prior changes from `data/feedback/implementations.yaml`.

For each candidate, match exact `url` first; use a weak secondary match only for clearly related `new-page` or query-cluster opportunities. Use these fields: `date_implemented`, `suggestion_type`, `change`, `status`, `min_impressions_for_eval`, `baseline`, `evaluation`.

Treat history as decision support:

- avoid repeating the same recommendation too soon
- recognize cooldown / observation windows
- surface pages that are ready to evaluate
- use prior outcomes as weak priors, not hard blocks

### History-aware states

Every meaningful item must have one `history_state`:

- `new-opportunity`
- `recently-changed-wait`
- `ready-to-evaluate`
- `follow-up-needed`
- `repeat-recommendation-blocked`

Apply these rules:

- Cooldown: default to a 14-day wait after `date_implemented`; during cooldown, avoid another major `rewrite` / `refresh` / `expand` / `new-page` unless evidence is unusually strong.
- Evaluation-ready: if `status: pending` and current impressions meet `min_impressions_for_eval`, prefer `history_state: ready-to-evaluate`, put the item in follow-ups, and usually use `defer`.
- Duplicate recommendation: if the new idea is substantially the same as a recent implementation, mark `repeat-recommendation-blocked` and use `defer`.
- Follow-up-needed: only use when there is a materially different or clearly remaining problem, especially outside cooldown.
- Weak priors: mention poor past outcomes in notes, but do not suppress an obviously important finding solely because of them.

### Prioritization

Rank roughly in this order:

1. Declining pages with no recent implementation
2. Pages ready to evaluate a prior implementation
3. Strong new opportunities with no history
4. Evidence-based follow-ups after a prior implementation
5. Recently changed pages still in cooldown
6. Duplicate recommendations

## Output Requirements

### Report file

Write `reports/YYYY-MM-DD/report.md` with exactly these sections:

- `# SEO Analysis`
- `## Top New Findings`
- `## Implementation Follow-Ups`
- `## Deferred Or Low-Confidence Items`

Keep `Top New Findings` + `Implementation Follow-Ups` to **8 items max** combined.

Write `reports/YYYY-MM-DD/findings.yaml` containing the same YAML payload that you save into propagate context for `:findings`.

### Finding format

Use this structure for every item in `Top New Findings`, `Implementation Follow-Ups`, and any meaningful deferred item:

```markdown
### <short finding title>
- Page: `/path/` or `n/a`
- Primary query or query set: `...`
- Search Intent: `...`
- Diagnosis: `meta` | `intent-mismatch` | `content-depth` | `content-quality` | `structure` | `new-page-opportunity` | `technical`
- Why it matters now: `<one-sentence decision signal>`
- Evidence:
  - `impressions: ...`
  - `clicks: ...`
  - `ctr: ...`
  - `position: ...`
  - `trend: Declining|Stable|Improving|New`
  - `engagement: content-problem|content-weak|content-delivers|low-confidence|n/a`
- SEO history:
  - `history_state: new-opportunity|recently-changed-wait|ready-to-evaluate|follow-up-needed|repeat-recommendation-blocked`
  - `has_prior_implementation: true|false`
  - `last_implemented: YYYY-MM-DD|n/a`
  - `prior_change: ...|n/a`
  - `prior_status: pending|evaluated|n/a`
  - `evaluation_readiness: below-threshold|ready|n/a`
  - `duplicate_of_prior_change: true|false`
- Recommended action class: `rewrite` | `refresh` | `expand` | `trim` | `new-page` | `defer`
- Notes for planning: `<brief recommendation>`
```

Rules:

- Every item must have exactly one recommended action class.
- If the next step is observation or evaluation, use `defer` and say why.
- Do not use `rewrite` or `refresh` for `intent-mismatch`.
- Do not use `new-page` unless the current page is missing or clearly the wrong target.
- Put low-volume, low-confidence, cooldown, and duplicate items in `Deferred Or Low-Confidence Items`, except `ready-to-evaluate` items, which belong in `Implementation Follow-Ups`.
- Always mention relevant prior implementations in `Notes for planning`.

### Save findings to context

Save grouped findings to `:findings` with this exact top-level shape:

```bash
propagate context set --stdin --global :findings <<'FINDINGS'
report_date: YYYY-MM-DD
top_new_findings:
  - title: ...
    page: /path/
    query: ...
    search_intent: ...
    diagnosis: meta
    why_now: ...
    evidence:
      impressions: 123
      clicks: 4
      ctr: 0.0325
      position: 6.4
      trend: Declining
      engagement: content-weak
    history:
      history_state: new-opportunity
      has_prior_implementation: false
      last_implemented: null
      prior_change: null
      prior_status: null
      min_impressions_for_eval: null
      evaluation_readiness: n/a
      duplicate_of_prior_change: false
    recommended_action_class: refresh
    notes_for_planning: ...
implementation_follow_ups:
  - title: ...
    page: /path/
    history:
      history_state: ready-to-evaluate
    recommended_action_class: defer
deferred_or_low_confidence:
  - title: ...
    page: /path/
    reason: recently implemented; still within cooldown window
    history:
      history_state: recently-changed-wait
FINDINGS
```

Save the same YAML payload to `reports/YYYY-MM-DD/findings.yaml` so later runs can reuse it without recomputing the analysis.

When in doubt, prefer `defer` over churn and prefer evaluating prior implementations before creating net-new work.
