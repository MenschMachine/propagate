# Generate SEO Suggestions

Read `:findings` from context. Turn each finding into a typed, actionable suggestion.

If there are PR comments from a previous review (visible in context), address that feedback and revise your suggestions accordingly.

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
