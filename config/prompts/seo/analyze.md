# Analyze SEO Data

Process Google Search Console (GSC) and PostHog data to identify actionable SEO opportunities. Output a concise list of findings for the `plan-seo` step.

## Inputs
Read data paths from global context:
```bash
propagate context get --global :gsc-data-path
propagate context get --global :posthog-data-path
```
*(Skip engagement quality analysis if PostHog data is missing.)*

## 1. Analysis Focus

**Performance & Content:**
- **Low CTR**: Impressions ≥ 50, CTR < 3%.
- **Position Drops**: Impressions > 20, unexpected rank drop.
- **Striking Distance**: Ranking positions 4–20.
- **Intent Mismatch**: Queries landing on the wrong page.
- **Technical/Indexing**: Zero clicks despite impressions, or suspect URL patterns.

**Engagement Quality (Requires PostHog):**
Classify pages based on bounce rate:
- `content-problem`: > 70% (poor delivery)
- `content-weak`: 50–70% (mediocre)
- `content-delivers`: < 40% (good engagement)
- `low-confidence`: < 5 pageviews.

**Trend Analysis:**
Evaluate metrics over the last 4 weeks. Look in `reports/` (last 4 `report.md` files) or fallback to raw GSC JSON in `data/*/pages/` (use `pages` section, NOT `query_page`). Classify trends:
- **Declining**: Worsening over multiple weeks (highest priority).
- **Stable**: No meaningful change.
- **Improving**: Trending upward.
- **New**: First appearance.

## 2. Optional Enrichments

**Intent Match:**
```bash
propagate context get --global :intent-match
```
If available, include the intent-match table. Use intent data to override diagnosis (e.g., label as intent mismatch instead of a meta issue).

**Page Content Diagnosis:**
```bash
ls data/*/pages/*.json 2>/dev/null | head -1
```
If found, load page JSONs (filename is URL path, alphanumeric replaced with `_`, e.g., `how_to_redact_pdfs.json`):
- **Meta Alignment**: Check if `title` and `meta_description` contain primary query terms. *Must include current indexed title/description in the report.*
- **Thin Content**: ~500 words or missing H1 entirely.
- **Implementation Status**: Use `deployment_status` from `:evaluation-results` (`not_yet_indexed` = technical finding, `confirmed_indexed` = skip, `unknown` = skip).

**Enrichment Data:**
```bash
ls -d data/enrichment/*/ 2>/dev/null | sort -r | head -1
```
If found, use `competitors-*.json` (for striking distance context) and `keyword-opportunities-*.json` (new keyword targets).

## 3. Output Requirements

**1. Write Report**: Save to `reports/YYYY-MM-DD/report.md` with exactly this structure:
- `# SEO Analysis`
- `## Top Findings` (Max 8 items)
- `## Deferred Or Low-Confidence Items`
- *(Optional supporting sections for enrichments)*

**2. Top Finding Format**:
```markdown
### <short finding title>
- Page: `/path/` or `n/a`
- Primary query or query set: `...`
- Diagnosis: `meta`, `intent-mismatch`, `content-depth`, `content-quality`, `structure`, `new-page-opportunity`, or `technical`
- Why it matters now: `<one sentence with the decision signal>`
- Evidence:
  - `impressions: ...`
  - `clicks: ...`
  - `ctr: ...`
  - `position: ...`
  - `trend: Declining|Stable|Improving|New`
  - `engagement: content-problem|content-weak|content-delivers|low-confidence|n/a`
- Recommended action class: `rewrite`, `refresh`, `expand`, `trim`, `new-page`, or `defer`
- Notes for planning: `<brief page-facing recommendation>`
```

**3. Rules**:
- Every top finding must have exactly **one** recommended action class.
- If `defer`, explain why.
- Don't use `rewrite`/`refresh` if the issue is `intent-mismatch`.
- Don't use `new-page` unless the current page is wrong/missing.
- Always include current title/description for `meta` diagnosis.
- Put low-volume/cool-down URLs in `Deferred`.

**4. Save Findings to Context**:
Save a compact, structured representation of findings/deferrals to `:findings`.
```bash
propagate context set --stdin --global :findings <<'FINDINGS'
<your structured findings>
FINDINGS
```
