# Analyze SEO Data

Read the data files referenced in global `:gsc-data-path`. Analyze the GSC performance data to identify actionable opportunities.

Also read PostHog analytics data if available (path in global `:posthog-data-path`). This provides per-page engagement metrics (bounce rate, session duration) that complement GSC's search performance data.

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

**Fallback when fewer than 2 report directories exist:** Compute trends directly from the raw GSC weekly exports in `data/`. Use the `pages` section of each GSC JSON file (not `query_page` aggregation) to match the GSC page-level API methodology. The `pages` section contains pre-aggregated per-page metrics from Google; the `query_page` section uses a different aggregation that will produce different numbers for the same page.

Classify each flagged page as:
- **Declining**: metrics worsening over multiple weeks — highest priority
- **Stable**: no meaningful change
- **Improving**: metrics trending upward — lower priority unless still underperforming
- **New**: first appearance in reports — note as such

Prioritize multi-week declines over single-week dips. A page that dropped once may be noise; a page declining 3+ weeks needs attention.

## Implementation effectiveness (read-only)

The `evaluate-implementations` step has already evaluated the ledger and saved results to global context. Read them:

```bash
propagate context get --global :evaluation-results
```

If evaluation results exist, include an **Implementation Effectiveness** section at the top of the report, before
per-category findings. Reproduce the evaluation summary (newly evaluated entries, pending progress, pattern summary)
and incorporate it into `:findings` so the suggest step has:
- Which URLs are in cool-down (`pending`)
- Which suggestion types are working or failing (`improved` / `declined`)
- Which URLs to deprioritize (`inconclusive` with `insufficient_volume`)

**Fallback when evaluation results are unavailable:** If `:evaluation-results` is empty or the context read fails, read the ledger file directly:

```bash
cat data/feedback/implementations.yaml 2>/dev/null
```

If the ledger exists and contains entries, extract all URLs with `status: pending` and include them in `:findings` as cool-down entries. The suggest step must know about these URLs even if the evaluate step did not run. Do not attempt to evaluate entries (that is the evaluate step's job) — just pass through the pending URLs, their `date_implemented`, and their `suggestion_type` so the suggest step can skip them.

Do **not** modify `data/feedback/implementations.yaml` — the evaluate-implementations execution owns all ledger writes.

## Output

Write a structured report to `reports/YYYY-MM-DD/report.md` (use today's date). The report should have sections for each category above with specific pages/queries and data points.

The findings should be a concise, actionable list that the suggest execution can turn into specific changes.

These shared run-level data keys are stored in global context. To read them, run exactly:
```bash
propagate context get --global :gsc-data-path
```

```bash
propagate context get --global :posthog-data-path
```

If `:posthog-data-path` is empty or the file doesn't exist, skip all engagement quality analysis — same pattern as enrichment data.

To save findings, run exactly:
```bash
propagate context set --stdin --global :findings <<'FINDINGS'
<your structured findings>
FINDINGS
```

## Intent match (optional)

Read intent-match data from the previous step:
```bash
propagate context get --global :intent-match
```

If available, include the intent-match table and mismatch summary in `:findings`.

Cross-reference: when a page appears in both intent-match and other sections (CTR issues, content diagnosis), let the intent data inform the diagnosis. A low-CTR page with an intent mismatch is a mismatch problem, not a meta problem. A high-bounce page with a clear intent mismatch should be flagged as intent-driven rather than content-quality-driven.

If `:intent-match` is empty or the context read fails, skip this section.

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

**When flagging a page with a `description` or `title` diagnosis, always include the actual current indexed values in the report:**
- Current title: `<title value from page JSON>`
- Current description: `<meta_description value from page JSON>`

Do not write "not provided" or omit the current values — if the page JSON exists, extract and report them. These values are needed by the suggest step to generate concrete meta suggestions.

### b) Thin content detection

Use `text_content` word count as a rough signal. Threshold: ~500 total words (we're catching thin pages vs substantive ones, not drawing a fine line).
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
