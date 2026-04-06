# Implement SEO Changes

You are editing a public website for real visitors.

The one approved planning PR already contains the implementation briefs for this run. Those briefs are evidence-backed
implementation inputs, not final copy to paste blindly. Use them to understand what problem needs to be fixed on each
page, then implement that fix in the natural voice and structure of the `pdfdancer-www` site.

SEO is the diagnostic input, not the voice of the page.

## Review feedback (check first)

Before doing anything else, run:
```bash
propagate context get :pr-comments
```
This returns a JSON object with two keys:
- `comments`: issue-style PR comments (general feedback on the PR)
- `review_comments`: line-specific diff comments (reviewer feedback on specific lines)

If there are review_comments, they are the reviewer's feedback on your previous implementation. Address every comment — fix what was asked, revert what was rejected, and note what you changed. This takes priority over everything below.

---

Fetch the approved implementation briefs by running exactly:
```bash
propagate context get :implementation-briefs --task plan-seo
```

If a refined local brief exists from a prior review pass, use it instead:

```bash
propagate context get :active-implementation-briefs
```

Implement those approved briefs on the `pdfdancer-www` site. In one run, that may mean both editing existing pages
and creating new ones.

## Guidelines

Read `AGENTS.md` in the pdfdancer-www repository root for site architecture, conventions, and implementation patterns. It has everything you need.

Match the existing code style. Don't refactor unrelated code.

## Editorial perspective

For every change, work from this perspective:

- What is the visitor trying to understand, decide, or accomplish on this page?
- What is currently weak or missing?
- What is the clearest, most useful way to fix that inside the existing site voice?

The result should read like intentional website content written for users, not like output from an SEO workflow.

Use the briefs to determine:

- the problem to solve
- the topics or terms that matter
- the structural changes needed
- the constraints you should respect

Do not treat brief wording as mandatory body copy.

## Content rules

Apply these standards to all new or revised public-facing content:

- Headings should describe a real topic, task, comparison, or benefit.
- Body copy should help the reader understand something, decide something, or complete something.
- Internal links should feel helpful in context, not mechanically inserted.
- FAQs should contain plausible user questions and useful answers.
- New sections should fit the page's existing purpose instead of turning the page into a generic SEO landing page.

Avoid copy that sounds like editorial scaffolding, optimization notes, or process narration. Public copy should not read
like a summary of the change you just made.

## Working method

Prefer `:active-implementation-briefs` when present; otherwise use the approved briefs from `plan-seo`.

For each brief:

1. Identify the user-facing job the page needs to do better.
2. Inspect the surrounding page structure and tone.
3. Decide whether the job is to edit an existing page or create a new one.
4. Implement the smallest coherent change that actually improves the page.
4. Rewrite awkward or mechanical phrasing until it reads naturally in context.

## Final self-check

Before finishing, review your own diff as a website editor:

- Would a real visitor naturally understand this wording?
- Do headings describe content rather than the editing process?
- Does each new section earn its place on the page?
- If the SEO workflow context were hidden, would these edits still make sense?
- Is anything phrased like an internal note instead of public content?

If any answer is no, revise the content before continuing.

## Tracking changed URLs

After making changes, collect the list of production URLs (https://pdfdancer.com/...) that were modified or created.

To save the changed URLs, run exactly:
```bash
propagate context set --stdin :changed-urls <<'URLS'
["https://pdfdancer.com/page1/", "https://pdfdancer.com/page2/"]
URLS
```
