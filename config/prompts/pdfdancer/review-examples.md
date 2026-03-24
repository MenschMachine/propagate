You are reviewing changes that were automatically generated to propagate an SDK capability to the examples project.

Inspect the current diff:

```bash
git diff main --stat
git diff main
```

Check that the new examples:

- Actually work
- Are clean
- Are easy to understand
- Are as simple as possible to showcase the capability

Your job is to review the examples code. Infrastructure, like GitHub Actions, is none of your business.

Classify each finding into one of the following categories:

**BLOCKING** — issues in THIS repository that must be fixed:
- Examples that do not work or produce wrong results
- Missing examples for new capabilities
- Broken imports or dependencies

**NON-BLOCKING** — improvements in THIS repository that are nice-to-have:
- Examples that could be simpler or clearer
- Style or formatting inconsistencies
- Comments that could be improved

**UPSTREAM BUG** — a bug in the upstream SDK that makes examples incorrect. File a GitHub issue against the upstream SDK repository for the language you are working on and store the URL:

```bash
ISSUE_URL=$(gh issue create --repo MenschMachine/<upstream-sdk-repo> --title "<concise title>" --body "<description>")
propagate context set :upstream-bug "$ISSUE_URL"
```

**UPSTREAM IMPROVEMENT** — a suggestion for the upstream SDK that does not affect correctness here. File a GitHub issue against the upstream SDK repository:

```bash
gh issue create --repo MenschMachine/<upstream-sdk-repo> --title "<concise title>" --body "<description>"
```

Do not write to any review key for upstream improvements.

If there are BLOCKING issues, be specific about file names and what needs to change:

```bash
propagate context set --stdin :review-findings <<'FINDINGS'
<your blocking findings>
FINDINGS
```

If there are NON-BLOCKING suggestions:

```bash
propagate context set --stdin :review-suggestions <<'SUGGESTIONS'
<your non-blocking suggestions>
SUGGESTIONS
```

If everything looks good, do not write to any review key.
