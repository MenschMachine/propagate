# Stage 6 Test Task

Test only the final-stage addition to Propagate: multi-repository orchestration and deterministic DAG execution.

## Test goals

1. Exercise success and failure paths for repository lookup and working-directory selection.
2. Confirm DAG scheduling order is deterministic across repositories.
3. Confirm existing repository-local signals and propagation triggers still work inside the DAG model.
4. Confirm clear failures for missing repositories, invalid edges, and dependency cycles.
5. Fix defects directly if you find them.

## Scope guard

Do not add parallel execution, background coordination services, retries, or a stage 7 target.
