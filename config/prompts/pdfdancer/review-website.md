You are reviewing changes that were automatically generated to propagate documentation updates to the website.

Inspect the current diff:

```bash
git diff main --stat
git diff main
```

Check for:

- **Accuracy** — does the website content correctly reflect the documentation changes?
- **Presentation** — is the content well-structured and clear for end users?
- **Links** — are all links valid and pointing to the right destinations?
- **Consistency** — does it follow the existing website style and conventions?

Your job is to review the website content. Infrastructure, like GitHub Actions, is none of your business.

Classify each finding into one of the following categories:

**BLOCKING** — issues in THIS repository that must be fixed:
- Website content that does not correctly reflect the documentation
- Broken links
- Incorrect or misleading information

**NON-BLOCKING** — improvements in THIS repository that are nice-to-have:
- Presentation or structure improvements
- Wording that could be clearer
- Style inconsistencies

**UPSTREAM BUG** — a bug in `MenschMachine/pdfdancer-api-docs` that makes the website content incorrect. File a GitHub issue and store the URL:

```bash
ISSUE_URL=$(gh issue create --repo MenschMachine/pdfdancer-api-docs --title "<concise title>" --body "<description>")
propagate context set :upstream-bug "$ISSUE_URL"
```

**UPSTREAM IMPROVEMENT** — a suggestion for `MenschMachine/pdfdancer-api-docs` that does not affect website correctness. File a GitHub issue:

```bash
gh issue create --repo MenschMachine/pdfdancer-api-docs --title "<concise title>" --body "<description>"
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
