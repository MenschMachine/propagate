Prepare the PR body for this client SDK repository.

Read:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,url
  API_PR_NUMBER="$(propagate context get :api-pr-number --task implement-pdfdancer-api | xargs)"
else
  API_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
fi
gh pr view "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json title,url
```

Resolve the exact PR body context key from `PROPAGATE_EXECUTION` and store the final body there:

```bash
case "${PROPAGATE_EXECUTION}" in
  implement-client-typescript) PR_BODY_KEY=":client-typescript-pr-body" ;;
  implement-client-python) PR_BODY_KEY=":client-python-pr-body" ;;
  implement-client-java) PR_BODY_KEY=":client-java-pr-body" ;;
  *)
    echo "Unsupported SDK execution: ${PROPAGATE_EXECUTION}" >&2
    exit 1
    ;;
esac
```

Write the final body with a command equivalent to:

```bash
propagate context set "${PR_BODY_KEY}" "<final body>"
```

Structure:

- `## Source API PR`
- If the run started from a backend merge, also include `## Source Backend PR`
- short summary of the SDK changes
- `## Verification`
- `## Downstream Follow-Up` describing the examples stage
