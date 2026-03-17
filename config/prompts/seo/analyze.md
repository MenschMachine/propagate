# Analyze SEO Data

Read the data files referenced in `:gsc-data-path`. Analyze the GSC performance data to identify actionable opportunities.

Also read PostHog analytics data if available (path in `:posthog-data-path`). This provides per-page engagement metrics (bounce rate, session duration) that complement GSC's search performance data.

## What to analyze

### Performance issues
- Pages with high impressions but low CTR (< 3%) — likely need better meta titles/descriptions
- Pages that dropped in average position compared to what you'd expect for their impression volume
- Queries where pdfdancer ranks 4-20 (striking distance of page 1 or top 3)

### Content gaps
- Queries from GSC that land on the wrong page (intent mismatch)

### Engagement quality (optional — requires PostHog data)

If PostHog data is available, cross-reference bounce rate per page with GSC-flagged pages and classify each as:
- `content-problem` — bounce rate > 70%. Visitors land but leave immediately; the page itself isn't delivering.
- `content-weak` — bounce rate 50–70%. Engagement is mediocre; may respond to content improvements.
- `content-delivers` — bounce rate < 40%. Visitors engage with the content; the page is doing its job.

Flag pages with fewer than 5 pageviews as **low-confidence** — the bounce rate is not statistically meaningful.

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
propagate context get :evaluation-results --task evaluate-implementations/evaluate
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

To read the data paths, run exactly:
```bash
propagate context get :gsc-data-path
```

```bash
propagate context get :posthog-data-path
```

If `:posthog-data-path` is empty or the file doesn't exist, skip all engagement quality analysis — same pattern as enrichment data.

To save findings, run exactly:
```bash
propagate context set :findings "<your structured findings>"
```

## Page content diagnosis (optional)

Check if page content data exists:
```bash
ls data/*/pages/*.json 2>/dev/null | head -1
```

If found, load page JSON files from the `pages/` subdirectory of the latest data directory for each GSC-flagged page. The filename derives from the URL path: strip leading/trailing slashes, then replace all non-alphanumeric characters with `_`, add `.json`. For example, `/how-to/redact-pdfs/` becomes `how_to_redact_pdfs.json`.

### a) Title/description vs. query alignment

For each flagged page, check whether the indexed `title` and `meta_description` contain the primary query terms from GSC:
- If title aligns with queries but CTR is still low → the problem is description, competition, or content depth — not the title
- If title doesn't contain query terms at all → flag as meta alignment issue

### b) Thin content detection

Use `text_content` word count as a rough signal. Threshold: ~1000 total words (we're catching 200-word pages vs 2000-word pages, not drawing a fine line).
- Solid meta but very low word count → flag "content depth" as the issue
- Missing H1 entirely → flag as a structural finding

### c) Implementation mismatch detection

If `:evaluation-results` contains a `deployment_status` list, use it directly — the evaluate-implementations script has
already compared `indexed_at_implementation` snapshots against current page content. Do not re-derive this.

- Entries with `"status": "not_yet_indexed"` → surface as a technical finding (change not picked up by search engines yet)
- Entries with `"status": "confirmed_indexed"` → note as deployed, no action needed
- Entries with `"status": "unknown"` → skip

Include the diagnosis type per page (title-alignment, description, content-depth, structural, mismatch) and the engagement quality signal (`content-problem`, `content-weak`, `content-delivers`, or `low-confidence`) in `:findings` so the suggest step can use both.

If no `pages/` directory exists, skip this section entirely.

## Enrichment data (optional)

Check if enrichment data exists:
```bash
ls -d data/enrichment/*/ 2>/dev/null | sort -r | head -1
```

If found, read the JSON files inside:
- `competitors-*.json`: Add competitor context to striking-distance analysis — who ranks above pdfdancer, their titles/descriptions, SERP features present
- `keyword-opportunities-*.json`: Add a "New keyword opportunities" section — keywords with search volume that pdfdancer doesn't rank for, prioritized by relevance to PDF tools/SDK/API

If no enrichment directory exists, skip this section entirely.
