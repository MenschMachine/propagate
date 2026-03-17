# Analyze SEO Data

Read the data files referenced in `:gsc-data-path`. Analyze the GSC performance data to identify actionable opportunities.

## What to analyze

### Performance issues
- Pages with high impressions but low CTR (< 3%) — likely need better meta titles/descriptions
- Pages that dropped in average position compared to what you'd expect for their impression volume
- Queries where pdfdancer ranks 4-20 (striking distance of page 1 or top 3)

### Content gaps
- Queries from GSC that land on the wrong page (intent mismatch)

### Technical signals
- Pages with zero clicks despite impressions
- URL patterns that suggest indexing issues

## Significance thresholds
Only flag items with meaningful impact potential:
- Minimum 50 impressions for CTR analysis
- Position changes only matter if the page had > 20 impressions

## Trend analysis

Look back at the last 4 weeks of reports to understand how metrics are moving over time:

```bash
ls reports/ | sort -r | head -4
```

Read the `report.md` from each past report directory and extract metrics for pages flagged in the current analysis. Present trends inline with your findings, e.g.:

> CTR: 2.1% → 1.4% → 0.58% (declining 3 weeks)

Classify each flagged page as:
- **Declining**: metrics worsening over multiple weeks — highest priority
- **Stable**: no meaningful change
- **Improving**: metrics trending upward — lower priority unless still underperforming
- **New**: first appearance in reports — note as such

Prioritize multi-week declines over single-week dips. A page that dropped once may be noise; a page declining 3+ weeks needs attention.

## Implementation effectiveness (read-only)

The `evaluate-implementations` step has already evaluated the ledger and saved results to context. Read them:

```bash
propagate context get :evaluation-results --task evaluate
```

If evaluation results exist, include an **Implementation Effectiveness** section at the top of the report, before
per-category findings. Reproduce the evaluation summary (newly evaluated entries, pending progress, pattern summary)
and incorporate it into `:findings` so the suggest step has:
- Which URLs are in cool-down (`pending`)
- Which suggestion types are working or failing (`improved` / `declined`)
- Which URLs to deprioritize (`inconclusive` with `insufficient_volume`)

Do **not** modify `data/feedback/implementations.yaml` — the evaluate-implementations execution owns all ledger writes.

## Output

Write a structured report to `reports/YYYY-MM-DD/report.md` (use today's date). The report should have sections for each category above with specific pages/queries and data points.

The findings should be a concise, actionable list that the suggest execution can turn into specific changes.

To read the data path, run exactly:
```bash
propagate context get :gsc-data-path
```

To save findings, run exactly:
```bash
propagate context set :findings "<your structured findings>"
```

## Enrichment data (optional)

Check if enrichment data exists:
```bash
ls -d data/enrichment/*/ 2>/dev/null | sort -r | head -1
```

If found, read the JSON files inside:
- `competitors-*.json`: Add competitor context to striking-distance analysis — who ranks above pdfdancer, their titles/descriptions, SERP features present
- `keyword-opportunities-*.json`: Add a "New keyword opportunities" section — keywords with search volume that pdfdancer doesn't rank for, prioritized by relevance to PDF tools/SDK/API

If no enrichment directory exists, skip this section entirely.
