# Summarize Fetched SEO Data

Look at the data files that were just pulled into the `data/` directory (today's date folder).

Read the GSC data (path in `:gsc-data-path`).

Write a brief summary noting:
- Total queries and pages in GSC data
- Top 10 queries by clicks
- Top 10 pages by impressions
- Any anomalies (zero-click pages with high impressions, position drops, etc.)

To read the data path, run exactly:
```bash
propagate context get :gsc-data-path
```

To save the summary, run exactly:
```bash
propagate context set :data-summary "<your summary>"
```
