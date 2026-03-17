# SEO Feedback Loop

Tracks which suggestions were implemented, snapshots baseline metrics, and automatically evaluates before/after
performance in subsequent runs.

## Overview

```
Weekly run:
  pull-data → evaluate-implementations → analyze → suggest → implement → track-implementations → request-index
                     ↑                                                          |
                     └──────────── reads ledger entries written by ─────────────┘
```

Two executions own the ledger (`data/feedback/implementations.yaml`), with clear separation:
- **track-implementations**: appends new `pending` entries (after implement)
- **evaluate-implementations**: scores `pending` → `evaluated` entries (before analyze)

No other execution writes to the ledger. `analyze` reads it (via context) to include in reports. `suggest` reads
effectiveness data from `:findings` only.

## Implementation Ledger

**File**: `data/feedback/implementations.yaml` in pdfdancer-marketing-data, committed to main.

Each entry:

```yaml
- url: /sdk/nodejs/
  suggestion_type: meta
  change: "Rewrote title tag and meta description"
  date_implemented: 2026-03-17
  suggestion_source: reports/2026-03-16/suggestions.md
  min_impressions_for_eval: 655
  baseline:
    weeks:
      - period: "2026-02-24 to 2026-03-02"
        impressions: 310
        clicks: 2
        ctr: 0.65
        position: 11.2
      - period: "2026-03-03 to 2026-03-09"
        impressions: 345
        clicks: 2
        ctr: 0.58
        position: 10.46
      - period: "2026-03-10 to 2026-03-16"
        impressions: 320
        clicks: 3
        ctr: 0.94
        position: 10.8
      - period: "2026-03-17 to 2026-03-23"
        impressions: 335
        clicks: 2
        ctr: 0.60
        position: 10.5
    averages:
      impressions: 327.5
      clicks: 2.25
      ctr: 0.69
      position: 10.73
  status: pending
  evaluation: null
```

### Fields

| Field | Description |
|---|---|
| `url` | Page path that was changed |
| `suggestion_type` | `meta`, `content-edit`, `new-content`, `technical` |
| `change` | Human-readable summary of what was done |
| `date_implemented` | Date the change was applied |
| `suggestion_source` | Path to suggestions file, or `"context-only"` if not written to a report file |
| `min_impressions_for_eval` | Post-change impressions needed before evaluation |
| `baseline.weeks` | Raw per-week GSC metrics for the trailing 4 weeks before implementation |
| `baseline.averages` | Convenience averages across the 4 baseline weeks (for PR readability) |
| `status` | `pending` → `evaluated` |
| `evaluation` | Written by evaluate-implementations when scored (see below) |

### Calculating `min_impressions_for_eval`

Multiply the baseline average weekly impressions by a factor based on suggestion type:

| Type | Multiplier | Rationale |
|------|-----------|-----------|
| `meta` | 2x | CTR changes show up relatively quickly |
| `content-edit` | 3x | Needs re-crawl + re-ranking |
| `new-content` | 4x | Needs discovery + indexing + ranking |
| `technical` | 2x | Usually binary — fixed or not |

Example: a page averaging 100 impressions/week with a `content-edit` needs 300 post-change impressions.

### Multiple entries per URL

A URL can have multiple ledger entries over time. Deduplication rule: skip if the URL already has a `pending` entry.
But if the previous entry is `evaluated`, a new `pending` entry can be appended — this happens when a URL is
re-implemented after a previous evaluation cycle.

## Evaluation Gates

An entry is ready for evaluation when **both** conditions are met:

1. **Calendar floor**: at least 14 days since `date_implemented` (GSC reporting lag)
2. **Volume gate**: the page has accumulated >= `min_impressions_for_eval` impressions since `date_implemented`

**90-day ceiling**: if 90 days pass without meeting both gates, evaluate anyway and mark as `inconclusive` with reason
`insufficient_volume`. This prevents zombie entries and signals that the page isn't worth optimizing further — the
suggest step should deprioritize future recommendations for it.

The 90-day ceiling is checked at evaluation time (when evaluate-implementations runs), not enforced by a timer. If runs
are skipped or delayed, entries may linger past 90 days until the next run picks them up.

## Evaluation States

| State | Meaning |
|---|---|
| `improved` | Change exceeds noise threshold in the right direction |
| `declined` | Change exceeds noise threshold in the wrong direction |
| `inconclusive` | Directionally positive or negative but within noise band, OR hit the 90-day ceiling |
| `no_change` | Metric stayed flat within expected variance |

### Noise threshold

Computed at evaluation time (not hardcoded in the ledger). The evaluate-implementations step has the full picture:
baseline variance, post-change data, and the type of change.

Approach:
1. Determine the primary metric by suggestion type: CTR for `meta`/`content-edit`, impressions for `new-content`,
   position for `technical`
2. Compute standard deviation of the primary metric across `baseline.weeks`
3. Compare post-change average vs `baseline.averages` for that metric
4. If delta > 2x std dev → `improved` or `declined` (depending on direction)
5. If delta < 2x std dev but directional → `inconclusive`
6. If delta near zero → `no_change`

"Better" depends on the metric: higher CTR and impressions are better, lower position is better.

This is a sanity check, not rigorous statistical testing — at these volumes you need "this looks real" vs "this could
be random."

### Evaluated entry example

```yaml
- url: /sdk/nodejs/
  # ... (all fields from above) ...
  status: evaluated
  evaluation:
    date: 2026-04-07
    state: improved
    reason: "CTR increased from 0.69% avg to 2.1% over 3 weeks post-change, >2x baseline std dev (0.16%)"
    post_change:
      weeks:
        - period: "2026-03-31 to 2026-04-06"
          impressions: 330
          clicks: 7
          ctr: 2.12
          position: 9.8
      impressions_accumulated: 980
```

## Execution: `track-implementations`

Runs on pdfdancer-marketing-data. Triggers after `implement` completes. Sole owner of ledger **append** writes.

**Tasks**:
1. Read `:changed-urls` and `:suggestions` from implement/suggest context (cross-execution reads)
2. Match each changed URL to its suggestion for type and change description
3. Pull trailing 4 weeks of GSC data as baseline (raw weeks + averages)
4. Calculate `min_impressions_for_eval` using the type multiplier
5. Append entries to `data/feedback/implementations.yaml`
6. Commit to main

## Execution: `evaluate-implementations`

Runs on pdfdancer-marketing-data. Triggers after `pull-data` completes (so it has fresh GSC data). Sole owner of
ledger **evaluation** writes.

**Tasks**:
1. Read `data/feedback/implementations.yaml`
2. For each `pending` entry, check evaluation gates
3. Score mature entries using the noise threshold
4. Write evaluated results back to the ledger
5. Save `:evaluation-results` summary to context for analyze to read
6. Commit to main

## Data flow to downstream steps

- **analyze**: reads `:evaluation-results` from evaluate-implementations context. Includes an Implementation
  Effectiveness section in the report. Passes effectiveness data through to `:findings`.
- **suggest**: reads `:findings` from analyze. Uses the effectiveness data for cool-down (pending URLs), pattern
  matching (what works), and deprioritization (insufficient_volume). Does **not** read the raw ledger file.

## Future improvement

The statistical evaluation logic (std dev, classification) is currently handled by the agent in
evaluate-implementations. If this proves unreliable, it can be migrated to a Python script (following the
`scripts/fetch_gsc.py` pattern in marketing-data) with the agent just interpreting the results.
