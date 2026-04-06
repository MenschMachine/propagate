# Create Rewrite Editorial Briefs

You are converting approved SEO strategy items into editorial briefs for existing pages.

Do not write website copy here. Write implementation-ready briefs for editors.

## Inputs

Read the strategy:

```bash
propagate context get :strategy-path --task plan-seo
cat "$(propagate context get :strategy-path --task plan-seo)"
```

Read the selected rewrite targets:

```bash
propagate context get :rewrite-targets --task plan-seo
```

Read prior review feedback if present:

```bash
propagate context get :review-findings || true
propagate context get :review-suggestions || true
propagate context get :revision-reason || true
```

## Brief requirements

Create `reports/YYYY-MM-DD/briefs/rewrite-briefs.yaml`.

Each brief entry must include:

- `target`
- `change_type`
- `page_type`
- `priority`
- `primary_audience`
- `visitor_state`
- `page_role`
- `current_problem`
- `page_promise`
- `must_cover`
- `sections_to_add_or_rework`
- `proof_points`
- `relevant_internal_links`
- `constraints`
- `out_of_scope`
- `acceptance_criteria`

## Framing rules

- Use page-editor language only.
- Translate internal SEO reasoning into visitor, page-role, and section-structure language.
- Do not describe the page as funnel architecture.
- Make the brief specific enough that an editor can revise the page without making new product decisions.
- If you are revising after `:review-findings`, resolve those issues directly instead of rewriting the brief from
  scratch.

## Required context keys

Set:

```bash
propagate context set :rewrite-briefs-path "reports/YYYY-MM-DD/briefs/rewrite-briefs.yaml"
```

```bash
propagate context set --stdin :rewrite-briefs <<'BODY'
<full contents of rewrite-briefs.yaml>
BODY
```
