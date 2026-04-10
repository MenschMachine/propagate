# Create SEO Issues

Read the findings from the analysis step:

```bash
propagate context get --global :findings
```

For each finding where `Recommended action class` is not `defer`, check for a duplicate GitHub issue and create one if none exists.

## Duplicate check

Before creating an issue, search for existing issues with the same title:

```bash
gh issue list --repo MenschMachine/pdfdancer-www --state all --search "SEO: <short title>" --json title --jq '.[].title'
```

If a matching issue already exists, skip it.

## Create the issue

```bash
gh issue create \
  --repo MenschMachine/pdfdancer-www \
  --title "SEO: <short title>" \
  --label "seo" \
  --body "<body>"
```

The title should be a concise description of the finding (under 80 characters).

The body should include:

```
**Page:** <page path or n/a>
**Diagnosis:** <diagnosis type>
**Recommended action:** <action class>

**Evidence:**
<evidence lines from finding>

**Notes:**
<notes for planning from finding>
```

Process all non-deferred findings. Do not set any context keys.
