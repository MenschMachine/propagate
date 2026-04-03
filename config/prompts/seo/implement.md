# Implement SEO Changes

You are editing a public website for real visitors.

The approved suggestions are evidence-backed implementation briefs, not final copy to paste blindly. Use them to
understand what problem needs to be fixed on the page, then implement that fix in the natural voice and structure of
the `pdfdancer-www` site.

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

Fetch the approved suggestions by running exactly:
```bash
propagate context get :suggestions --task suggest
```

Implement those suggestions on the pdfdancer-www site.

## Guidelines

Read `AGENTS.md` in the pdfdancer-www repository root for site architecture, conventions, and implementation patterns. It has everything you need.

Match the existing code style. Don't refactor unrelated code.

## Editorial perspective

For every change, work from this perspective:

- What is the visitor trying to understand, decide, or accomplish on this page?
- What is currently weak or missing?
- What is the clearest, most useful way to fix that inside the existing site voice?

The result should read like intentional website content written for users, not like output from an SEO workflow.

Use the suggestions to determine:

- the problem to solve
- the topics or terms that matter
- the structural changes needed
- the constraints you should respect

Do not treat suggestion wording as mandatory body copy unless the suggestion explicitly provides exact `meta` text.

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

For each suggestion:

1. Identify the user-facing job the page needs to do better.
2. Inspect the surrounding page structure and tone.
3. Implement the smallest coherent change that actually improves the page.
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
