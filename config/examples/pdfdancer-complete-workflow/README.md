# Testing `pdfdancer-complete-workflow` Without Merging Again

This bundle lets you start the workflow from a local signal file instead of waiting for a real GitHub webhook.

Use an already merged `MenschMachine/pdfdancer-backend` PR number so the prompts can still run their `gh pr view` /
`gh pr diff` commands successfully.

## 1. Pick a real merged backend PR number

Find one:

```bash
gh pr list --repo MenschMachine/pdfdancer-backend --state merged --limit 10
```

Take one PR number from that list and replace `123` in the sample signal files below.

## 2. Start from the merged-PR signal file

Edit:

- `signals/backend-pr-merged.yaml`

Then run:

```bash
venv/bin/propagate run \
  --config config/pdfdancer-complete-workflow.yaml \
  --signal-file config/examples/pdfdancer-complete-workflow/signals/backend-pr-merged.yaml
```

This exercises:

- signal parsing
- initial execution selection
- backend validation
- pipeline decision

It does not require a new merge event.

## 3. Test the approval loops under `serve`

For end-to-end loop testing, run the workflow in long-lived mode:

```bash
venv/bin/propagate serve --config config/pdfdancer-complete-workflow.yaml
```

In another terminal, send the starting signal:

```bash
venv/bin/propagate send-signal \
  --project pdfdancer-complete-workflow \
  --signal-file config/examples/pdfdancer-complete-workflow/signals/backend-pr-merged.yaml
```

Then replay downstream review labels with the sample files in `signals/` after replacing the PR numbers with the ones
the workflow created.

Examples:

```bash
venv/bin/propagate send-signal \
  --project pdfdancer-complete-workflow \
  --signal-file config/examples/pdfdancer-complete-workflow/signals/api-approved.yaml
```

```bash
venv/bin/propagate send-signal \
  --project pdfdancer-complete-workflow \
  --signal-file config/examples/pdfdancer-complete-workflow/signals/api-changes-required.yaml
```

## 4. Useful stop/resume pattern

To test only the first stage:

```bash
venv/bin/propagate run \
  --config config/pdfdancer-complete-workflow.yaml \
  --signal-file config/examples/pdfdancer-complete-workflow/signals/backend-pr-merged.yaml \
  --stop-after triage-backend-pr
```

Then continue later:

```bash
venv/bin/propagate run \
  --config config/pdfdancer-complete-workflow.yaml \
  --resume
```

## Notes

- The downstream approval signal files are templates. Replace the repository and PR number fields before using them.
- `pull_request.closed` only starts the workflow when `merged: true`.
- Review loops match on the exact downstream repo and PR number, so replaying a label against the wrong PR will be ignored.
