# Stage 6 Implementation Task

Implement only the final-stage addition to Propagate: multi-repository orchestration and deterministic DAG execution.

## Required outputs

1. Update `propagate.py` to support config-defined repositories.
2. Route executions to configured repository working directories.
3. Support dependency edges between executions.
4. Schedule runnable executions deterministically until the DAG completes or fails.
5. Keep existing repository-local signals and propagation triggers compatible with the DAG model.
6. Fail clearly on invalid repository config, invalid dependencies, cycles, or missing working directories.

## Constraints

- Keep the implementation in `propagate.py`
- Preserve existing repository-local behavior
- Keep prompt-file substitution via `{prompt_file}`
- Keep `PyYAML` as the only external dependency
- Do not add parallel execution, background workers, retries, or a stage 7 target

Verify the updated CLI manually after editing.
