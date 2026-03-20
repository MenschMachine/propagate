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

If there are issues, list each one clearly so the implementing agent can fix them. Be specific about file names and what needs to change. Store your findings:

```bash
propagate context set :review-findings "<your detailed findings>"
```

If everything looks good, do not write to `:review-findings`.
