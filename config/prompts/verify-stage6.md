# Stage 6 Verify Task

Verify only the final-stage multi-repository and DAG behavior in `propagate.py`.

## Verify these outcomes

1. Config-defined repositories are parsed correctly.
2. Executions run in the intended repository working directory.
3. Dependency edges produce deterministic DAG scheduling.
4. Existing repository-local signals and propagation triggers remain compatible.
5. Failures are clear for invalid repositories, invalid dependencies, and cycles.

If anything is missing or incorrect, fix it directly. Do not add parallel execution, background workers, retries, or a stage 7 target.
