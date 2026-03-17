# Track Implementations

Record which suggestions were implemented so that future evaluation runs can measure before/after performance. This
execution is the sole owner of appending new entries to the ledger — no other execution adds entries.

## Steps

### 1. Read implementation details from context

```bash
propagate context get :changed-urls --task implement
```

```bash
propagate context get :suggestions --task suggest
```

`:changed-urls` is a JSON array of production URLs. `:suggestions` is the structured suggestion list from the suggest
step. Both are cross-execution context reads — the context store is shared across executions regardless of which
repository they operate on.

### 2. Match URLs to suggestions

For each changed URL, find the corresponding suggestion to extract:
- `suggestion_type`: meta | content-edit | new-content | technical
- `change`: a one-line summary of what was done

If a URL doesn't match any suggestion cleanly, use `content-edit` as the default type and describe the change
generically.

### 3. Collect baseline metrics

Find the most recent 4 weeks of GSC data:

```bash
ls data/ | grep -E '^[0-9]{4}-' | sort -r | head -4
```

For each changed URL, extract weekly GSC metrics (impressions, clicks, CTR, position) from those 4 data directories.
Strip the domain to match against the GSC data (e.g., `https://pdfdancer.com/sdk/nodejs/` becomes `/sdk/nodejs/`).

If a week has no data for the URL (e.g., zero impressions), include it as zeroes — don't skip it, as that's meaningful
baseline information.

Compute `baseline.averages` as the mean across all 4 baseline weeks.

### 4. Calculate `min_impressions_for_eval`

Multiply the baseline average weekly impressions by a factor based on suggestion type:

| Type | Multiplier |
|------|-----------|
| meta | 2x |
| content-edit | 3x |
| new-content | 4x |
| technical | 2x |

Formula: `avg_weekly_impressions * multiplier`

Example: a page averaging 100 impressions/week with a `content-edit` suggestion needs 300 post-change impressions
before it can be evaluated.

### 5. Find the suggestion source path

Look for the most recent suggestions file:

```bash
find reports/ -name "*suggest*" | sort -r | head -1
```

Use that path as `suggestion_source`. If no file matches, use `"context-only"` as a fallback — the suggestions were
stored in the context store but not written to a report file.

### 6. Write the ledger

Read the existing ledger if present:

```bash
cat data/feedback/implementations.yaml 2>/dev/null || echo "[]"
```

Append new entries. Deduplication rule: skip a URL if it already has a `pending` entry. But if the URL's previous entry
is `evaluated`, append a new `pending` entry — a URL can be re-implemented after a previous evaluation cycle.

Write the updated ledger to `data/feedback/implementations.yaml`. Create the `data/feedback/` directory if it doesn't
exist.

### Entry schema

Each entry must follow this exact structure:

```yaml
- url: /sdk/nodejs/
  suggestion_type: meta
  change: "Rewrote title tag and meta description"
  date_implemented: 2026-03-17
  suggestion_source: reports/2026-03-16/suggestions.md
  min_impressions_for_eval: 650
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
