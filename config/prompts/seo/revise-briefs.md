# Revise Implementation Briefs

You are revising implementation briefs because implementation review found that the brief itself was too abstract, too
strategy-shaped, or otherwise not directly writable.

## Inputs

Read the approved briefs:

```bash
propagate context get :implementation-briefs --task plan-seo
```

Read the blocking brief findings from the latest review pass:

```bash
propagate context get :review-findings-brief
```

## Task

Rewrite the briefs into a more implementation-ready form for the current run only.

Requirements:

- preserve the approved targets and overall strategic intent
- keep the typed `change_type` for each item
- remove strategy/funnel language and replace it with user/page language
- sharpen the page promise, core reader questions, proof, constraints, and boundaries
- leave enough editorial judgment for implementation to choose the exact section structure
- do not split the briefs back into rewrite and new-content artifacts

Do not edit repository files here. This is a local brief refinement for the implementation loop.

## Required context keys

Set:

```bash
propagate context set --stdin :active-implementation-briefs <<'BODY'
<refined briefs>
BODY
```

```bash
propagate context set :implementation-briefs-refined true
```
