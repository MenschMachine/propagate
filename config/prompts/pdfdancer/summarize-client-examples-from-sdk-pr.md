Prepare the PR body for this client examples repository.

Read the backend PR and the matching approved client SDK PR for this language. Summarize only what changed in this examples repository.

Resolve the exact PR body context key from `PROPAGATE_EXECUTION` and store the final body there:

```bash
case "${PROPAGATE_EXECUTION}" in
  implement-client-typescript-examples) PR_BODY_KEY=":client-typescript-examples-pr-body" ;;
  implement-client-python-examples) PR_BODY_KEY=":client-python-examples-pr-body" ;;
  implement-client-java-examples) PR_BODY_KEY=":client-java-examples-pr-body" ;;
  *)
    echo "Unsupported examples execution: ${PROPAGATE_EXECUTION}" >&2
    exit 1
    ;;
esac
```

Write the final body with a command equivalent to:

```bash
propagate context set --stdin "${PR_BODY_KEY}" <<'BODY'
<final body>
BODY
```

Structure:

- `## Source Backend PR`
- `## Source Client SDK PR`
- short summary of the examples changes
- `## Verification`
- `## Downstream Follow-Up`
