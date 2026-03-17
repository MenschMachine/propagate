# Evaluate Implementations

Read the implementation ledger and evaluate entries that have accumulated enough data. This execution is the sole owner
of evaluation writes to the ledger — no other execution modifies existing entries.

## Read the ledger

```bash
cat data/feedback/implementations.yaml 2>/dev/null
```

If the file doesn't exist or is empty, there's nothing to evaluate. Write a short summary to context and exit.

## Evaluate pending entries

For each entry with `status: pending`:

### 1. Check evaluation gates

Both conditions must be met:
1. **Calendar floor**: at least 14 days since `date_implemented`
2. **Volume gate**: the page has accumulated >= `min_impressions_for_eval` impressions since `date_implemented`

To check volume, find GSC data directories dated after `date_implemented`:

```bash
ls data/ | grep -E '^[0-9]{4}-' | sort
```

Read the GSC data from each post-implementation directory and sum impressions for the entry's URL.

**90-day ceiling**: if today is more than 90 days past `date_implemented` and the gates still aren't met, evaluate
anyway — mark as `inconclusive` with reason `insufficient_volume`. This is itself a signal: the page doesn't get enough
traffic to measure changes on.

If an entry doesn't pass any gate yet, skip it (leave as `pending`).

### 2. Classify the outcome

For entries that pass the gates, determine the primary metric based on suggestion type:
- `meta`: CTR
- `content-edit`: CTR
- `new-content`: impressions
- `technical`: position

Then:

1. From `baseline.weeks`, compute the **standard deviation** of the primary metric's weekly values
2. Collect the same metric from post-change weekly GSC data
3. Compute the **post-change average** for that metric
4. Compare against `baseline.averages` for the same metric
5. Classify:
   - **`improved`**: post-change average is better than baseline by more than 2x the baseline std dev
   - **`declined`**: post-change average is worse than baseline by more than 2x the baseline std dev
   - **`inconclusive`**: there's a directional change but it's within 2x std dev (could be noise)
   - **`no_change`**: delta is near zero, no meaningful direction

"Better" depends on the metric: higher CTR and impressions are better, lower position is better.

### 3. Write evaluation results

For each evaluated entry, update in place:
- Set `status: evaluated`
- Set `evaluation`:
  ```yaml
  evaluation:
    date: 2026-04-07
    state: improved
    reason: "CTR increased from 0.72% avg to 2.1% over 3 weeks post-change, >2x baseline std dev (0.19%)"
    post_change:
      weeks:
        - period: "2026-03-31 to 2026-04-06"
          impressions: 330
          clicks: 7
          ctr: 2.12
          position: 9.8
      impressions_accumulated: 980
  ```

Write the full updated ledger back to `data/feedback/implementations.yaml`.

## Save summary to context

Save a structured summary of evaluation results for the analyze step to include in its report:

```bash
propagate context set :evaluation-results "<your summary>"
```

The summary should include:
- Newly evaluated entries with outcomes and reasoning
- Pending entries with progress toward gates (e.g., "42 of 200 impressions, 10 of 14 days")
- Pattern summary: which suggestion types are working or failing across all evaluated entries
- Any URLs marked `inconclusive` with `insufficient_volume` (for suggest to deprioritize)

The 90-day ceiling is checked at evaluation time, not enforced by a timer. If runs are skipped or delayed, entries may
linger past 90 days until the next run picks them up.
