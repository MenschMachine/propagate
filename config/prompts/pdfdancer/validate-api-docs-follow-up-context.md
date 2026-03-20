This execution must continue from the workflow state created for the same source PR.

Validate:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  SOURCE_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,url,state,mergedAt
  propagate context get :pipeline-decision --task triage-backend-pr
else
  SOURCE_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
  gh pr view "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json number,title,url,state,mergedAt
  propagate context get :pipeline-decision --task triage-api-pr
fi
```

Optional upstream PRs that may exist in FULL mode:

```bash
propagate context get :api-pr-number --task implement-pdfdancer-api || true
propagate context get :client-typescript-examples-pr-number --task implement-client-typescript-examples || true
propagate context get :client-python-examples-pr-number --task implement-client-python-examples || true
propagate context get :client-java-examples-pr-number --task implement-client-java-examples || true
```

Fail fast unless the source PR exists and is merged.

Do not modify any files or write any code. This task is validation only — a workflow safety gate.
