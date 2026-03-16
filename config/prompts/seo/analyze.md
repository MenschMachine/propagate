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
