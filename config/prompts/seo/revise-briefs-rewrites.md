# Revise Rewrite Briefs

You are revising rewrite briefs because implementation review found that the brief itself was too abstract, too
strategy-shaped, or otherwise not directly writable.

## Inputs

Read the approved briefs:

```bash
propagate context get :rewrite-briefs --task brief-rewrites
```

Read the blocking brief findings from the latest review pass:

```bash
propagate context get :review-findings-brief
```

## Task

Rewrite the briefs into a more implementation-ready form for the current run only.

Requirements:

- preserve the approved page targets and overall strategic intent
- remove strategy/funnel language and replace it with user/page language
- replace templated section instructions with page promise, core reader questions, proof, and editorial guardrails
- sharpen page role and constraints without turning the brief into a fill-in-the-SEO-page worksheet
- leave no important editorial decisions open

Do not edit repository files here. This is a local brief refinement for the implementation loop.

## Required context keys

Set:

```bash
propagate context set --stdin :active-rewrite-briefs <<'BODY'
<refined briefs>
BODY
```

```bash
propagate context set :rewrite-briefs-refined true
```
