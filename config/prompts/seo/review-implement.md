# Review SEO Website Implementation

You are reviewing user-facing website changes generated from SEO implementation briefs.

Inspect the current diff:

```bash
git diff main --stat
git diff main
```

Review the diff as an editor responsible for the quality of `pdfdancer.com`.

Your job is not to ask whether the diff mechanically follows the suggestion text. Your job is to ask whether the final
website changes make sense for actual visitors and fit the site.

## Review perspective

Check:

- **User value** — do the changes make the page clearer, more useful, or more convincing for the intended visitor?
- **Editorial quality** — does the copy read naturally and confidently, rather than mechanically or awkwardly?
- **Page fit** — do the new headings, sections, links, and FAQs fit the page's purpose and existing structure?
- **Interpretation quality** — did the implementation correctly interpret the approved brief, or did it literalize internal reasoning into public copy?
- **Consistency** — does the content match the site's existing voice and conventions?

Pay special attention to weak AI-style failure modes:

- headings that describe process state instead of subject matter
- copy that sounds like internal analysis or editorial scaffolding
- FAQs or sections that answer questions no real visitor would ask
- generic filler added to satisfy structure without improving the page
- awkward phrasing that is technically related to the brief but wrong for the page

## Classification

Classify each finding into one of the following categories:

**BLOCKING** — issues in THIS repository that must be fixed:
- public content that feels unnatural, misleading, or obviously machine-generated
- headings or sections that do not make sense for real visitors
- literalized internal reasoning showing up in public copy
- structural changes that hurt clarity or page purpose
- implementation that misses the real intent of the approved brief

**NON-BLOCKING** — improvements in THIS repository that are nice-to-have:
- wording that works but could be sharper
- structure that is acceptable but could be cleaner
- links or section ordering that could be improved

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
