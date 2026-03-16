# Generate SEO Suggestions

Read `:findings` from context. Turn each finding into a typed, actionable suggestion.

If there are PR comments from a previous review (visible in context), address that feedback and revise your suggestions accordingly.

## Past suggestions and cool-down rules

Before generating suggestions, check what was previously recommended:

```bash
find reports/ -name "*suggest*" -o -name "*suggestion*" | sort -r
```

Follow these rules:

- **2-week cool-down**: Do not suggest changes for any URL that had a suggestion implemented less than 14 days ago. Give changes time to show up in GSC data before re-evaluating.
- **Don't repeat failures**: If the effectiveness review in `:findings` shows a past suggestion didn't improve the target metric, do not recommend the same approach again. Try a different angle or skip the page.
- **Build on successes**: If a type of change (e.g., meta title rewrites) consistently improved metrics across multiple pages, favor that approach for similar cases.
- **Note history when re-suggesting**: When suggesting changes for a page after the cool-down period, mention what was tried before and explain why the new suggestion takes a different approach.

## Grounding rules

Your only source of truth is `:findings`. Do not fabricate observations you did not make.

- **No invented evidence**: Do not claim to have fetched, inspected, or tested live pages unless `:findings` explicitly contains that data. Statements like "live fetches showed…" or "the HTML response contains…" are forbidden unless the analyze step actually performed and reported those checks.
- **Technical suggestions require evidence**: If you want to suggest a technical fix (missing tags, broken redirects, canonical issues), the underlying problem must be stated in `:findings`. If the findings only contain GSC performance data, your suggestions must be scoped to what that data supports — CTR copy improvements, content gaps, intent mismatches — not speculative infrastructure problems.
- **Say what you don't know**: If a technical issue seems plausible but isn't confirmed in the data, say so explicitly (e.g., "worth verifying whether the `<title>` tag is rendered server-side") instead of asserting it as fact.

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
