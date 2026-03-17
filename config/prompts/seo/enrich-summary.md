# Summarize DataForSEO Enrichment

Read the enrichment data that was just fetched. Find the latest enrichment directory:

```bash
ls -d data/enrichment/*/ 2>/dev/null | sort -r | head -1
```

Read both JSON files inside that directory:
- `competitors-*.json` — SERP competitor data for striking-distance keywords
- `keyword-opportunities-*.json` — related keyword opportunities not currently ranked

## What to summarize

1. **Keywords fetched** — how many keywords had SERP data pulled
2. **Top recurring competitors** — which domains appear most frequently in top positions across the checked keywords
3. **SERP features present** — which SERP features (featured snippets, people also ask, video, etc.) appear for pdfdancer's keywords
4. **New keyword opportunities** — how many new keywords were discovered, highlight any with high search volume (>500) or low difficulty (<30)

## Output

Write a brief summary to `data/enrichment/YYYY-MM-DD/summary.md` (inside the same dated directory as the JSON files) covering the points above.

Save the enrichment directory path to context so the analyze step can find it:

```bash
propagate context set :enrichment-path "<the directory path>"
```
