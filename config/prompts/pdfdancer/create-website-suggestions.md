# Create Website Suggestion Issue

<!-- propagate-required-labels: website_suggestions -->

This execution runs in the `pdfdancer-www` repository, but the triggering change lives in `pdfdancer-backend`.

## Inputs

Read the triggering PR number from signal context:

```bash
PR_NUMBER="$(propagate context get :signal.pr_number | xargs)"
MARKER="<!-- propagate:pdfdancer-website-suggestions source-pr=MenschMachine/pdfdancer-backend#$PR_NUMBER -->"
TITLE_PREFIX="Website suggestions for backend PR #$PR_NUMBER: "
```

Inspect the backend PR with:

```bash
gh pr view "$PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
gh pr diff "$PR_NUMBER" --repo MenschMachine/pdfdancer-backend
```

Then inspect the current website repo to decide how this backend work should appear on the site.

## Task

Create a GitHub issue in `MenschMachine/pdfdancer-www` describing whether and how this backend change should be featured on the website.

You must make this idempotent. Before creating anything, run this exact lookup and search for an existing open issue whose body contains the exact `MARKER` string:

```bash
gh issue list --repo MenschMachine/pdfdancer-www --state open --limit 200 --json number,title,body,url
```

If such an issue exists, update that issue. If not, create a new one. Do not rely on fuzzy title search.

Use this title format:

`$TITLE_PREFIX<backend PR title>`

The issue body must include this exact marker line near the top:

`$MARKER`

The issue body must include these sections:

1. `## Source PR`
2. `## Why This Matters On The Website`
3. `## Recommended API Docs Changes`
4. `## Recommended Website Changes`
5. `## Open Questions`

Rules:

- Ground every suggestion in the backend PR and the current website repo.
- Treat `pdfdancer-api-docs` as the first implementation target. The website recommendations should assume the api-docs changes land first.
- If no website update is warranted, still create or update the issue and say that explicitly.
- Be concrete. Name the relevant pages, sections, docs, examples, or navigation updates.
- If the `website_suggestions` label does not exist yet, create it before creating or updating the issue.
- Add or preserve the `website_suggestions` label on the issue.
- In `## Source PR`, include a direct backlink to `MenschMachine/pdfdancer-backend` PR `$PR_NUMBER`.
- Do not implement code changes in this execution. Only create or update the planning issue.
