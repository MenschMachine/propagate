Confirm that the local handoff is ready and restate which downstream executions should run next.

This prompt exists to show that a second sub-task can see context created by:

- the first sub-task's `after` hook
- a shell command in this sub-task's own `before` hook
