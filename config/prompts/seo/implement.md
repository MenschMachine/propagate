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

After making changes, collect the list of production URLs (https://pdfdancer.com/...) that were modified or created.

To read the suggestions from the suggest execution, run exactly:
```bash
propagate context get :suggestions --task suggest
```

To save the changed URLs, run exactly:
```bash
propagate context set :changed-urls '["https://pdfdancer.com/page1/", "https://pdfdancer.com/page2/"]'
```
