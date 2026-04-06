# Revise New-Content Briefs

You are revising new-content briefs because implementation review found that the brief itself was not strong enough to
support a high-quality new page.

## Inputs

Read the approved briefs:

```bash
propagate context get :new-content-briefs --task brief-new-content
```

Read the blocking brief findings:

```bash
propagate context get :review-findings-brief
```

## Task

Rewrite the briefs into a more implementation-ready form for the current run only.

Requirements:

- preserve the approved target pages and page types
- clarify why each page should exist separately
- sharpen audience, page role, and outline expectations
- remove strategy jargon and replace it with editorially usable direction

Do not edit repository files here. This is a local brief refinement for the implementation loop.

## Required context keys

Set:

```bash
propagate context set --stdin :active-new-content-briefs <<'BODY'
<refined briefs>
BODY
```

```bash
propagate context set :new-content-briefs-refined true
```
