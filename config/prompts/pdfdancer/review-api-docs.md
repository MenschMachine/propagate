You are reviewing changes that were automatically generated to propagate client SDK changes to the documentation project.

Inspect the current diff:

```bash
git diff main --stat
git diff main
```

Check for:

1. Do the provided code examples actually match the code in the client SDKs exactly?
2. Does the documentation cover all the new features and edge cases?
3. Are the provided code examples as simple as possible to showcase the new features?

Your job is to review the public documentation. Infrastructure, like GitHub Actions, is none of your business.

Classify each finding into one of the following categories:

**BLOCKING** — issues in THIS repository that must be fixed:
- Code examples that do not match the actual SDK code
- Missing documentation for new features or edge cases
- Code examples that are incorrect or would not compile/run

**NON-BLOCKING** — improvements in THIS repository that are nice-to-have:
- Documentation wording improvements
- Examples that could be simpler
- Formatting or structure suggestions

**UPSTREAM BUG** — a bug in an upstream SDK or API that makes the documentation incorrect. File a GitHub issue against the relevant upstream repository and store the URL:

```bash
ISSUE_URL=$(gh issue create --repo MenschMachine/<upstream-repo> --title "<concise title>" --body "<description>")
propagate context set :upstream-bug "$ISSUE_URL"
```

**UPSTREAM IMPROVEMENT** — a suggestion for an upstream SDK or API that does not affect documentation correctness. File a GitHub issue against the relevant upstream repository:

```bash
gh issue create --repo MenschMachine/<upstream-repo> --title "<concise title>" --body "<description>"
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
