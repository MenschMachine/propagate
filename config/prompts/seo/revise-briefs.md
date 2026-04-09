# Revise Implementation Briefs

You are revising implementation briefs because implementation review found that the brief itself was too abstract, too
strategy-shaped, or otherwise not directly writable.

## Inputs

Read the approved briefs:

```bash
propagate context get --global :implementation-briefs
```

Read the blocking brief findings from the latest review pass:

```bash
propagate context get :review-findings-brief
```

## Task

Rewrite the briefs into a more implementation-ready form for the current run only.

Requirements:

- preserve the approved `page.path` targets and overall strategic intent
- keep the typed `page.change_type` for each item
- remove strategy/funnel language and replace it with user/page language
- sharpen the goal, page promise, message priorities, approved claims, and implementation boundaries
- leave enough editorial judgment for implementation to choose the exact section structure
- keep `must_change`, `can_change`, and `must_keep` clearly separated
- keep `success_criteria` observable in the final page copy
- do not split the briefs back into rewrite and new-page artifacts

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
