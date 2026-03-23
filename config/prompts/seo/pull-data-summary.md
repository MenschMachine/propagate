# Summarize Fetched SEO Data

Look at the data files that were just pulled into the `data/` directory (today's date folder).

Read the GSC data (path in `:gsc-data-path`).

Also read PostHog analytics data if available (path in `:posthog-data-path`).

Write a brief summary noting:
- Total queries and pages in GSC data
- Top 10 queries by clicks
- Top 10 pages by impressions
- Any anomalies (zero-click pages with high impressions, position drops, etc.)
- Top bounce rate pages (highest bounce rates from PostHog)
- Low-bounce candidates (pages with bounce rate < 40% that may be underperforming in search)
- Tracking gaps (GSC pages missing from PostHog or vice versa)

To read the data paths, run exactly:
```bash
propagate context get :gsc-data-path
```

```bash
propagate context get :posthog-data-path
```

If `:posthog-data-path` is empty or the file doesn't exist, skip the PostHog-related summary bullets.

To save the summary, run exactly:
```bash
propagate context set --stdin :data-summary <<'BODY'
<your summary>
BODY
```
