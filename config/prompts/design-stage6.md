# Stage 6 Design Task

Design only the final-stage addition to Propagate: multi-repository orchestration and deterministic DAG execution.

## Deliverable

Write an implementation-ready design note at `docs/multi-repo-and-dag-stage-6-design.md`.

## Scope

Describe only:

1. Repository definitions in config.
2. Execution-to-repository routing.
3. Dependency edges between executions.
4. Deterministic DAG scheduling across repositories.
5. How existing signals and propagation triggers interact with the DAG.
6. Repository-scoped context storage and working-directory selection.
7. Failure handling for missing repositories, invalid edges, cycles, and cross-repo execution failures.

## Constraints

- Keep the runtime in `propagate.py`
- Preserve existing repository-local execution behavior
- Use the existing local process model only
- Do not add parallel execution, retries, background workers, or a stage 7 target

Do not implement code in this sub-task unless a tiny clarification edit is unavoidable.
