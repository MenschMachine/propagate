Read the backend PR that triggered this workflow and decide whether downstream code implementation is required.

Inputs:

- `PR_NUMBER="$(propagate context get :signal.pr_number | xargs)"`
- `gh pr view "$PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json number,title,body,files,url,mergedAt,headRefName,baseRefName`
- `gh pr diff "$PR_NUMBER" --repo MenschMachine/pdfdancer-backend`

Tasks:

1. Store the backend PR number for downstream executions:

```bash
propagate context set :source-backend-pr-number "$PR_NUMBER"
propagate context set --global :source-pr-number "$PR_NUMBER"
propagate context set --global :source-repository "MenschMachine/pdfdancer-backend"
propagate context set --global :source-kind backend
```

2. Decide the pipeline:
   - If the backend PR changes public API behavior, SDK-facing wire contracts, generated artifacts, client-facing interfaces, or examples that must be implemented in code, choose FULL.
   - If it only requires documentation and website follow-up, choose DOCS.

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
