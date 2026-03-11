# Stage 6 Refactor Task

Refactor only the final-stage multi-repository and DAG implementation in `propagate.py`.

## Refactor goals

1. Improve clarity and maintainability of the repository-routing and DAG-scheduling code.
2. Preserve existing repository-local execution behavior.
3. Keep scheduling deterministic and explicit.
4. Do not expand scope beyond stage 6.

## Constraints

- Keep the implementation in `propagate.py`
- Keep `PyYAML` as the only external dependency
- Reuse explicit repository-scoped context handling
- Do not add parallel execution, hidden state, or a new bootstrap target
