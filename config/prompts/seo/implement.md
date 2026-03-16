# Implement SEO Changes

Read `:suggestions` from context. Implement the approved suggestions on the pdfdancer-www Gatsby site.

If there are PR comments from a previous review (visible in context), address that feedback and revise your implementation.

## Guidelines

- This is a Gatsby React site. Pages are in `src/pages/`, components in `src/components/`.
- For **meta** changes: update the SEO/Head component props, page metadata, or Gatsby Head API exports.
- For **content-edit** changes: modify the relevant page or component content directly.
- For **new-content**: create new pages following the existing site structure and conventions.
- For **technical** changes: update gatsby-config, add redirects, fix canonical tags, etc.
- Match the existing code style. Don't refactor unrelated code.

## Tracking changed URLs

After making changes, collect the list of URLs that were modified or created. Save them to context so the indexing step can request re-crawling:

```
propagate context set :changed-urls '["https://pdfdancer.com/page1/", "https://pdfdancer.com/page2/"]'
```

Use the production URLs (https://pdfdancer.com/...), not localhost.
