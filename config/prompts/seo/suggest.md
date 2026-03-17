# Generate SEO Suggestions

## Review feedback (check first)

Before doing anything else, run:
```bash
propagate context get :review-comments
```
If this returns review comments, they are the reviewer's feedback on your previous suggestions. Address every comment — fix what was asked, drop what was rejected, and note what you changed. This takes priority over everything below.

---

Read `:findings` from context. Turn each finding into a typed, actionable suggestion.

## Past suggestions and cool-down rules

The `:findings` from the analyze step include an **Implementation Effectiveness** section with evaluation results from
the feedback ledger. Use that data to apply these rules:

- **Pending = cool-down**: Any URL listed as `pending` in the effectiveness data is still being evaluated. Do not suggest new changes for it.
- **Don't repeat failures**: If a URL's previous suggestion was evaluated as `declined`, do not recommend the same suggestion type. Try a different approach or skip the page entirely.
- **Build on successes**: If entries evaluated as `improved` share a common suggestion type (e.g., meta rewrites), favor that approach for similar pages.
- **Deprioritize low-volume pages**: If a URL was marked `inconclusive` with `insufficient_volume`, deprioritize it. Changes on pages that can't accumulate enough impressions to measure aren't worth optimizing further.
- **Note history when re-suggesting**: When suggesting changes for a page with prior evaluations in `:findings`, mention what was tried before, the outcome, and why the new suggestion takes a different approach.

## Grounding rules

Your only source of truth is `:findings`. Do not fabricate observations you did not make.

- **No invented evidence**: Do not claim to have fetched, inspected, or tested live pages unless `:findings` explicitly contains that data. Statements like "live fetches showed…" or "the HTML response contains…" are forbidden unless the analyze step actually performed and reported those checks.
- **Page content is factual when present**: When `:findings` contains page content diagnosis for a URL (from the analyze step's page content checks), you CAN reference the indexed title, description, content depth, and mismatches as factual observations — these come from actual fetched page data.
- **Technical suggestions require evidence**: If you want to suggest a technical fix (missing tags, broken redirects, canonical issues), the underlying problem must be stated in `:findings`. If the findings only contain GSC performance data, your suggestions must be scoped to what that data supports — CTR copy improvements, content gaps, intent mismatches — not speculative infrastructure problems.
- **Say what you don't know**: If a technical issue seems plausible but isn't confirmed in the data, say so explicitly (e.g., "worth verifying whether the `<title>` tag is rendered server-side") instead of asserting it as fact.

### Suggestion type selection based on page content diagnosis

When `:findings` includes a page content diagnosis type, use it to guide your suggestion type:
- **Title aligns with queries but low CTR** → description-focused `meta` or `content-edit`
- **Thin content** (low word count) → `content-edit`, not `meta` — the problem is substance, not packaging
- **Source vs. indexed mismatch** (implementation not picked up) → `technical`
- **Title missing query terms** → `meta` (title-focused)

### Example: grounded vs. ungrounded suggestion

**Well-grounded** (page content data exists in findings):
> The page snapshot for `/sdk/fastapi/` returned HTTP 200 with no title, meta description, H1, or body text. This is a render/indexability problem. Fix the page so the HTML response exposes indexable content.

**Poorly grounded** (speculative, no page content evidence):
> The page at `/sdk/fastapi/` likely has a weak title tag that doesn't match query intent. Rewrite the title to include "FastAPI PDF SDK."

The first version cites what was actually observed. The second invents a diagnosis from GSC performance data alone — it could be right, but it could also be wrong (the real problem might be rendering, thin content, or something else entirely). When page content data is available, use it. When it isn't, say what you don't know.

### Suggestion type selection based on engagement quality signal

When `:findings` includes an engagement quality classification from PostHog bounce rate data, use it to further refine the suggestion type:

- **`content-problem`** (bounce > 70%) → prefer `content-edit`. The page isn't delivering — improving meta to drive more traffic to a broken page makes things worse.
- **`content-weak`** (bounce 50–70%) → use the page content diagnosis to break the tie. If content is thin, go `content-edit`; if meta is misaligned, go `meta`.
- **`content-delivers` + low traffic** (bounce < 40%, few clicks) → prefer `meta` or `new-content`. This is a visibility problem — the page works, it just needs more eyes.
- **`content-delivers` + high traffic** → deprioritize. The page is performing well on both engagement and visibility.
- **`low-confidence`** (< 5 pageviews) → treat as if no engagement data exists; fall back to page content diagnosis only.

When the engagement signal conflicts with the page content diagnosis (e.g., content looks thin but bounce rate is low), trust the bounce rate — it reflects actual visitor behavior.

## Priority calibration

- **high**: Pages with 100+ impressions that have a confirmed diagnosis from page content data, or critical technical issues (e.g., pages returning empty HTML).
- **medium**: Pages with 50–100 impressions, or pages with 100+ impressions where the diagnosis is inferred from GSC data alone (no page content confirmation).
- **low**: Speculative opportunities, pages under 50 impressions, or hygiene fixes with minimal absolute impact (e.g., URL normalization on low-traffic pages).

## Suggestion count

Always include all high and medium priority suggestions. If the total count is below 10, fill up to 10 with low priority suggestions. Do not exceed 10 suggestions per run. If more opportunities exist beyond the cutoff, add a brief "Deferred opportunities" note at the end listing what was left out and why.

## How prescriptive to be

- **meta** suggestions: Write the exact title and description text. These are short, and you have enough data to get them right.
- **content-edit** and **new-content** suggestions: Provide the structure (headings, key phrases to include, internal links) but not full body copy. The implement step knows the site voice and can write better prose with access to the codebase.
- **technical** suggestions: Specify the exact fix (redirect rule, canonical tag, config change) — don't leave it vague.

## Suggestion types

### meta
Changes to page titles and meta descriptions. Include the current value (if known) and the suggested replacement.

### content-edit
Edits to existing page content — adding sections, rewriting copy, improving headings, adding internal links.

### new-content
New pages or blog posts to create. Include the target keyword, suggested URL slug, title, and content outline.

### technical
Technical SEO fixes — canonical tags, structured data, redirects, sitemap entries.

## Format

Write suggestions as a structured list. Be detailed and explicit — a reviewer reading the PR should fully understand the reasoning and know exactly what to do without needing to look anything up. For each suggestion include:

- **Type**: meta | content-edit | new-content | technical
- **Priority**: high | medium | low
- **Target**: URL or page path
- **What**: the specific change to make. Write out the exact text, markup, or configuration to add/change/remove. Do not leave anything vague or implied — spell it out so someone could implement it directly from this description.
- **Why**: explain the reasoning behind this suggestion. Reference the specific data points (e.g., "page has 500 impressions but only 0.5% CTR, well below the site average of 2.1%"), explain what the problem is, and why this particular change is expected to improve the situation. Connect the dots between the data and the recommendation.
- **Expected impact**: describe what improvement this change should produce and how it can be measured (e.g., "should increase CTR by making the title more compelling for the target query; track impressions-to-clicks ratio in GSC over the next 2 weeks")

## Output

Also write the suggestions into a file in the repository so they appear in the PR diff for review.

To read the findings from the analyze execution, run exactly:
```bash
propagate context get :findings --task analyze
```

To save your suggestions, run exactly:
```bash
propagate context set :suggestions "<your suggestions>"
```
