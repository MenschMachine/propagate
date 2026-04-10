# Create SEO Issues

Read the findings from the analysis step:

```bash
propagate context get --global :findings
```

For each finding where `Recommended action class` is not `defer`, check for a duplicate GitHub issue and create one if none exists.

## Duplicate check

Before creating an issue, search for existing open and closed issues:

```bash
gh issue list --repo MenschMachine/pdfdancer-www --state all --search "SEO: <short title>" --json title --jq '.[].title'
```

If a matching issue already exists, skip it.

## Issue title

`SEO: <concise description of the problem and page>` — under 80 characters.

Good examples:
- `SEO: Low CTR on /convert/ despite high impressions`
- `SEO: Intent mismatch on /sdk/java/ — rewrite for evaluators`
- `SEO: New page needed for "pdf redaction api" queries`

## Issue body

Write the body in this exact structure:

---

**Page:** `<page path or n/a>`
**Action:** `<rewrite|refresh|expand|trim|new-page>`
**Diagnosis:** `<meta|intent-mismatch|content-depth|content-quality|structure|new-page-opportunity|technical>`

---

### Why now

<The "why it matters now" sentence from the finding. One sentence, the decision signal.>

---

### Evidence

| Metric | Value |
|--------|-------|
| Impressions | ... |
| Clicks | ... |
| CTR | ... |
| Position | ... |
| Trend | Declining / Stable / Improving / New |
| Engagement | content-problem / content-weak / content-delivers / low-confidence / n/a |

Include the trend history inline if available, e.g.:
> CTR: 2.1% → 1.4% → 0.58% (declining 3 weeks)

---

### Queries driving this finding

List the primary query or query set from the finding, one per line with metrics if available:

- `<query>` — X impressions, pos Y.Z
- `<query>` — X impressions, pos Y.Z

---

### Current state

Include this section based on diagnosis type:

**For `meta` diagnosis:** include the actual indexed values:
- Current title: `<value>`
- Current description: `<value>`

**For `intent-mismatch`:** include the intent distribution if available from `:findings`:
- Visitor intent breakdown (e.g. Learning 60%, Evaluating 30%, Solving 10%)
- What the page currently serves vs. what the query intent demands

**For `content-depth`:** include word count and any structural signals (missing H1, etc.)

**For `technical`:** describe the specific technical issue (not yet indexed, zero clicks despite impressions, etc.)

---

### Competitor context

Include this section only if enrichment data was present in the finding. Show who ranks above pdfdancer for the primary queries, their titles/descriptions, and any notable SERP features.

If no enrichment data exists for this finding, omit this section entirely.

---

### What to do

Write concrete implementation instructions for a developer picking this up. Include:

1. **Change type:** what kind of change this is (`rewrite` = significant overhaul, `refresh` = targeted updates, `expand` = add content, `trim` = remove/tighten, `new-page` = create from scratch)
2. **Must change:** specific things that need to change — be concrete, not generic
3. **Must keep:** things that must stay intact (page path, required sections, links, component structure)
4. **Must avoid:** claims, patterns, or directions that would make this worse

**For `meta` diagnosis:** include a suggested title and description to use as a starting point:
- Suggested title: `<draft — must include primary query, under 60 chars>`
- Suggested description: `<draft — must reflect page promise and include query, under 155 chars>`

---

### Success criteria

Bullet list of observable outcomes that define done. Should be checkable by reading the final page:

- [ ] <concrete criterion>
- [ ] <concrete criterion>

---

## Labels

Apply these labels to every issue:
- `seo`
- the diagnosis type (e.g. `meta`, `intent-mismatch`, `content-depth`)
- the action class (e.g. `rewrite`, `refresh`, `new-page`)

Create the issue:

```bash
gh issue create \
  --repo MenschMachine/pdfdancer-www \
  --title "SEO: <title>" \
  --label "seo" \
  --label "<diagnosis>" \
  --label "<action-class>" \
  --body "<body>"
```

Process all non-deferred findings. Do not set any context keys.
