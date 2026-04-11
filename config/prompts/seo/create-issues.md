# Create SEO Issues

Read the findings from the analysis step:

```bash
propagate context get --global :findings
```

The `:findings` payload is grouped into:

- `top_new_findings`
- `implementation_follow_ups`
- `deferred_or_low_confidence`

Process the groups with these rules:

- create issues only from `top_new_findings`
- only consider `implementation_follow_ups` if an item explicitly has a non-`defer` `recommended_action_class`
- never create issues from `deferred_or_low_confidence`

For each eligible finding, check for a duplicate GitHub issue and create one if none exists.

## Issue title

Titles use a fixed slug so duplicate detection is reliable across runs:

- For findings with a page path: `SEO [/path/]: <concise description>`
- For `new-page` findings with no existing path: `SEO [query:<primary query>]: <concise description>`

Good examples:
- `SEO [/convert/]: Low CTR despite high impressions`
- `SEO [/sdk/java/]: Intent mismatch — rewrite for evaluators`
- `SEO [query:pdf redaction api]: New page opportunity`

Keep the full title under 80 characters.

## Duplicate check

Before creating an issue, search using the slug:

```bash
gh issue list --repo MenschMachine/pdfdancer-www --state all \
  --search "SEO [/path/]" --json title --jq '.[].title'
```

For `new-page` findings:

```bash
gh issue list --repo MenschMachine/pdfdancer-www --state all \
  --search "SEO [query:pdf redaction api]" --json title --jq '.[].title'
```

If any returned title contains the slug, an issue already exists. Fetch it:

```bash
gh issue list --repo MenschMachine/pdfdancer-www --state all \
  --search "SEO [/path/]" --json number,title,body,state --jq '.[0]'
```

Read the existing issue body and compare it against the new finding. Determine which of these four cases applies, then post a comment — do not create a new issue.

### Case 1: Validates

Same diagnosis, same action class, evidence pointing in the same direction. The problem persists.

Comment format:
```
**SEO re-analysis — YYYY-MM-DD** · Validates

Same problem confirmed. Updated metrics:

| Metric | Value |
|--------|-------|
| Impressions | ... |
| Clicks | ... |
| CTR | ... |
| Position | ... |
| Trend | ... |

<trend history if available, e.g. CTR: 2.1% → 1.4% → 0.58%>

Still recommended action: `<action class>`
```

### Case 2: Enriches

Same diagnosis and action class, but new data adds context that wasn't in the original — e.g. competitor data now available, intent breakdown added, additional queries surfaced.

Comment format:
```
**SEO re-analysis — YYYY-MM-DD** · Enriches

New data adds context to the original finding.

<describe specifically what is new — competitor entries, intent breakdown, additional queries, etc.>

Updated evidence:
| Metric | Value |
...
```

### Case 3: Contradicts

Different diagnosis or different action class. The original framing may be wrong or the problem has shifted.

Comment format:
```
**SEO re-analysis — YYYY-MM-DD** · Contradicts

New analysis suggests the real problem has changed. Please re-scope before starting work.

**Was:** `<original diagnosis>` → `<original action class>`
**Now:** `<new diagnosis>` → `<new action class>`

**Why:** <one sentence explaining what changed and why the new diagnosis is more accurate>

Updated evidence:
| Metric | Value |
...

Queries:
- `<query>` — X impressions, pos Y.Z
```

### Case 4: Outdated

Metrics have improved meaningfully or the original problem no longer appears in findings. The issue may no longer need doing.

Comment format:
```
**SEO re-analysis — YYYY-MM-DD** · Outdated

This page no longer appears as a top finding. The original problem may be resolved.

**Last known metrics:**
| Metric | Value |
...

Consider closing this issue if the page no longer shows the original symptoms.
```

Post the comment:

```bash
gh issue comment <number> --repo MenschMachine/pdfdancer-www --body "<comment>"
```

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

- [ ] A concrete criterion
- [ ] Another concrete criterion

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
  --title "SEO [/path/]: <description>" \
  --label "seo" \
  --label "<diagnosis>" \
  --label "<action-class>" \
  --body "<body>"
```

Do not set any context keys.
