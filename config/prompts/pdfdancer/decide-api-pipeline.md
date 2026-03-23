Read the open API PR labeled `propagate` that triggered this workflow and decide whether downstream code implementation is required.

Inputs:

- `PR_NUMBER="$(propagate context get :signal.pr_number | xargs)"`
- `gh pr view "$PR_NUMBER" --repo MenschMachine/pdfdancer-api --json number,title,body,files,url,state,headRefName,baseRefName`
- `gh pr diff "$PR_NUMBER" --repo MenschMachine/pdfdancer-api`

Tasks:

1. Store the source API PR number for downstream executions:

```bash
propagate context set :source-api-pr-number "$PR_NUMBER"
propagate context set --global :source-pr-number "$PR_NUMBER"
propagate context set --global :source-repository "MenschMachine/pdfdancer-api"
propagate context set --global :source-kind api
propagate context set --global :upstream-api-pr-number "$PR_NUMBER"
```

2. Decide the pipeline:
   - If the API PR changes public API behavior, generated SDK surface, client-facing interfaces, examples, or other changes that require SDK/example code follow-up, choose FULL.
   - If it only requires docs and website follow-up, choose DOCS.

3. Write exactly one of these context flags:

```bash
propagate context set --global run-full-pipeline true
```

or

```bash
propagate context set --global run-docs-pipeline true
```

4. Also save a short rationale for traceability:

```bash
DECISION="<FULL or DOCS>: <one-sentence reason>"
echo "$DECISION" | propagate context set --stdin :pipeline-decision
echo "$DECISION" | propagate context set --stdin --global :pipeline-decision
```

Be decisive. Do not set both flags.
