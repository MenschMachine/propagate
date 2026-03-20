This execution must continue from the backend PR selected by `triage-backend-pr`.

Validate:

- `BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"`
- `gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,url,state,mergedAt`
- `PIPELINE_DECISION="$(propagate context get :pipeline-decision --task triage-backend-pr | xargs)"`

Fail fast unless:

- the backend PR exists and is merged
- the pipeline decision starts with `FULL:`

Do not modify any files, write any code, or change context. This task is validation only — a workflow safety gate.
