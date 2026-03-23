# Intent-Match Analysis

Read GSC data from `:gsc-data-path` and classify the search intent behind each page's query traffic. This step produces an intent-match table that the analyze step uses to diagnose mismatches between what searchers want and what the page delivers.

## Data sources

To read the data paths, run exactly:
```bash
propagate context get :gsc-data-path
```

```bash
propagate context get :posthog-data-path
```

Check if page content data exists:
```bash
ls data/*/pages/*.json 2>/dev/null | head -1
```

## Scope

Only analyze pages with **50+ impressions** in the GSC `pages` section. Skip everything below that threshold.

If no pages meet the 50-impression threshold, save an explicit empty marker and skip the report:
```bash
propagate context set :intent-match "No pages qualified (all below 50 impressions)"
```
Do not write a report file. Stop here.

## Intent classification

For each in-scope page, collect all `query_page` rows that land on it. Classify each query into one of four intent stages:

- **Learning** — wants to understand. Signals: "what is", "how does", "why", question words, conceptual terms.
- **Evaluating** — comparing options. Signals: "best", "vs", "comparison", category terms like "pdf sdk" without a product name.
- **Solving** — wants to accomplish a task. Signals: language-specific terms, action verbs, error messages, "how to" + specific task.
- **Navigating** — looking for a known destination. Signals: brand name, "docs", "pricing", product-specific terms.

### Tiebreaker rules

When a query matches multiple stages:
- Brand + generic term → **Navigating**
- Language + task without brand → **Solving**
- Category + language without task → **Evaluating**
- Question + task → **Solving**

## Intent distribution

Compute intent distribution per page as **percentages weighted by impressions**, not by query count. A query with 500 impressions matters more than one with 5.

## Page stance

Determine what intent the page actually serves. Use page content data if available (load from `data/*/pages/*.json` — filename convention: strip leading/trailing slashes, replace all non-alphanumeric characters with `_`, add `.json`). If no page content exists, infer from the URL path.

Stance signals:
- **Learning** — explanatory prose, no code, conceptual framing
- **Evaluating** — comparisons, feature lists, differentiators
- **Solving** — code examples, step-by-step instructions, implementation details
- **Navigating** — product overview, assumes familiarity, landing-page structure

## Match assessment

Compare the dominant intent from query traffic against the page stance:

- **match** — intent aligns with stance
- **partial** — right direction but generic, templated, or shallow
- **mismatch** — different stages entirely

Flag **split-intent** pages where no single intent exceeds 70%.

## Output

Write a markdown table to `reports/YYYY-MM-DD/intent-match.md` (use today's date), sorted by impressions descending. Columns:

| Page | Learning % | Evaluating % | Solving % | Navigating % | Page Stance | Match | Bounce | Impr |

Formatting rules:
- **Bold** the dominant intent percentage
- Use `—` for 0%
- Include bounce rate from PostHog data if available; use `—` if not

Below the table, add a **Mismatch Summary** section with a one-line explanation per mismatched or partial page.

To save the output, run exactly:
```bash
propagate context set --stdin :intent-match <<'BODY'
<table and mismatch summary>
BODY
```
