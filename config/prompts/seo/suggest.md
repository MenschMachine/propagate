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

Write suggestions as a structured list. For each suggestion include:
- **Type**: meta | content-edit | new-content | technical
- **Priority**: high | medium | low
- **Target**: URL or page path
- **What**: specific change to make
- **Why**: the data point that motivates this (e.g., "page has 500 impressions, 0.5% CTR")

## Output

Save the full suggestions list to context:

```
propagate context set :suggestions "<suggestions>"
```

Also write the suggestions into a file in the repository so they appear in the PR diff for review.
