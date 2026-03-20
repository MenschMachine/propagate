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

If there are issues, list each one clearly so the implementing agent can fix them. Be specific about file names and what needs to change. Store your findings:

```bash
propagate context set :review-findings "<your detailed findings>"
```

If everything looks good, do not write to `:review-findings`.
