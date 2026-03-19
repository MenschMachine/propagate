# Validate Approved Website Suggestion Issue

This task must fail fast unless the triggering issue is one of the generated planning issues from this workflow.

## Inputs

Fetch the issue:

```bash
ISSUE_NUMBER="$(propagate context get :signal.issue_number | xargs)"
gh issue view "$ISSUE_NUMBER" --repo MenschMachine/pdfdancer-www --json title,body,url,labels
```

## Validation Rules

Treat the issue as valid only if all of these are true:

- The title starts with `Website suggestions for backend PR #`
- The body contains a hidden marker in this exact format:
  `<!-- propagate:pdfdancer-website-suggestions source-pr=MenschMachine/pdfdancer-backend#<number> -->`
- The body contains a `## Source PR` section with a direct backlink to the source backend PR
- The issue currently has the `website_suggestions` label

## Task

Perform the validation deterministically. If any rule fails, stop immediately and fail the task before any git branch is created.

If validation succeeds, do not edit code in this task. This task is only the workflow safety gate.
