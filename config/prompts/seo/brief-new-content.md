# Create New-Content Editorial Briefs

You are converting approved new-content strategy items into editorial briefs for brand-new pages.

Do not write page copy here. Write implementation-ready briefs for editors.

## Inputs

Read the strategy:

```bash
propagate context get :strategy-path --task plan-seo
cat "$(propagate context get :strategy-path --task plan-seo)"
```

Read the selected new-content targets:

```bash
propagate context get :new-content-targets --task plan-seo
```

## Brief requirements

Create `reports/YYYY-MM-DD/briefs/new-content-briefs.yaml`.

Each brief entry must include the same schema as rewrite briefs, plus:

- `new_page_purpose`
- `reason_to_exist_separately`
- `avoid_overlap_with`

For new-content pages, be especially clear about:

- why the page deserves to exist as its own destination
- what unique user need it serves
- how it differs from existing nearby pages

## Required context keys

Set:

```bash
propagate context set :new-content-briefs-path "reports/YYYY-MM-DD/briefs/new-content-briefs.yaml"
```

```bash
propagate context set --stdin :new-content-briefs <<'BODY'
<full contents of new-content-briefs.yaml>
BODY
```
