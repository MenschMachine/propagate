# Implement SEO Changes

You are editing a live website for real users.

Use implementation briefs to understand **what problem to fix**, not as copy to paste.  
SEO is diagnostic input, not the page voice.

Read docs/LANDING_PAGES.md and docs/CONTENT_GUIDELINE.md

---

## 0. Prior Review Failures (Check First)

```bash
propagate context get :revision-reason
```

If the output is `review-findings`, this is a **retry after a failed internal review**. Read the blocking findings:

```bash
propagate context get :prior-review-findings
```

**Address every finding before implementing anything else.** Each entry describes a specific, blocking problem in the previous implementation. Do not restate the fix in different words — resolve the underlying issue.

Common patterns that fail review:
- Headings that describe process or editorial state ("Why This Page Exists") — use subject-matter headings instead
- Vague compliance language ("Privacy-first defaults", "Compliance-ready operations") — use concrete, visitor-facing language
- Creating a new page without linking to it from the relevant hub or navigation

If `:revision-reason` is empty or `check-failure`, skip this section.

---

## 1. Review Feedback (Highest Priority)

Run:
```bash
propagate context get :pr-comments
```

- `review_comments` -> line-level feedback on your last changes  
- `comments` -> general PR feedback  

If `review_comments` exist:
- Address every comment
- Fix requested issues
- Revert rejected changes
- Note what you changed  

This overrides all other instructions.

---

## 2. Load Briefs

Prefer refined briefs:
```bash
propagate context get :active-implementation-briefs
```

Otherwise:
```bash
propagate context get --global :implementation-briefs
```

Implement all approved briefs. This may include editing existing pages and creating new ones.

---

## 3. Constraints

- Follow `AGENTS.md` (architecture, patterns)
- Follow `docs/CONTENT_GUIDELINE.md`
- Follow `docs/LANDING_PAGES.md`
- Match existing code and tone
- Do not refactor unrelated code

---

## 4. Editorial Approach

For each change:
- What is the visitor trying to understand, decide, or do?
- What is weak or missing?
- What is the clearest fix within the site’s voice?

Use briefs to extract:
- problem
- relevant topics/terms
- structural changes
- constraints

Do not reuse brief wording as-is.

---

## 5. Content Standards

- Headings -> real topics, tasks, or benefits  
- Body -> helps users understand, decide, or act  
- Links -> useful and natural  
- FAQs -> realistic questions, useful answers  
- Sections -> must fit the page’s purpose  

Avoid:
- SEO/process language
- editorial scaffolding
- “this page was optimized for…” phrasing

---

## 6. Working Method

For each brief:
1. Identify the user-facing job  
2. Review page structure and tone  
3. Decide: edit vs create  
4. Implement the smallest meaningful improvement  
5. Rewrite until it reads naturally  

---

## 7. Final Self-Check

Before finishing:
- Would a real user understand this?
- Do headings describe content (not process)?
- Does each addition earn its place?
- Would this make sense without SEO context?
- Any internal/editorial phrasing left?

If yes -> revise.

---

## 8. Track Changed URLs

After changes:
```bash
propagate context set --stdin --global :changed-urls <<'URLS'
["https://pdfdancer.com/page1/", "https://pdfdancer.com/page2/"]
URLS
```
