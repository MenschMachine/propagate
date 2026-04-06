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
- `core_reader_questions`
- `must_cover`
- `proof_points`
- `relevant_internal_links`
- `constraints`
- `out_of_scope`
- `acceptance_criteria`

You may add one optional field when it materially helps:

- `editorial_notes`

Do not require a fixed section list. The brief should explain what the page needs to accomplish and what substance it
needs, while leaving final section naming and some structural judgment to implementation.

## Framing rules

- Use page-editor language only.
- Translate internal SEO reasoning into reader needs, page substance, proof, and editorial guardrails.
- Do not describe the page as funnel architecture, intent-routing, or page ownership mechanics.
- Do not prescribe generic section templates such as "comparison block", "evaluation section", "who this is for", or
  "next steps" unless the page truly cannot work without that exact module.
- Prefer concrete reader questions over abstract content-planning labels.
- Make the brief specific enough that an editor can revise the page without inventing product strategy, but open enough
  that the editor still writes a real page rather than filling in a template.
- If you are revising after `:review-findings`, resolve those issues directly instead of rewriting the brief from
  scratch.

## What A Good Brief Sounds Like

Good:

- what a visitor is trying to understand or decide
- what proof the page needs to provide
- what distinctions or boundaries the page must make
- what kinds of examples or use cases should anchor the page

Bad:

- instructions that read like content-architecture notes
- prescribed headings that sound generic before they are written
- strategy labels such as owning demand, routing intent, evaluation-stage framing, or cluster repair

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
