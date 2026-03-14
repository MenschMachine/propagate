from collections.abc import Callable
from dataclasses import replace

from .constants import LOGGER
from .errors import PropagateError
from .models import ExecutionConfig, GitRunState, RuntimeContext
from .sub_tasks import run_execution_sub_tasks, run_hook_phase


def run_configured_execution(
    execution: ExecutionConfig,
    runtime_context: RuntimeContext,
    completed_task_ids: set[str] | None = None,
    on_task_completed: Callable[[str, str], None] | None = None,
) -> None:
    LOGGER.info("Running execution '%s' with %d sub-task(s).", execution.name, len(execution.sub_tasks))
    git_state = GitRunState() if execution.git else None
    ctx = replace(runtime_context, git_state=git_state)
    context_id = f"execution '{execution.name}'"
    try:
        run_hook_phase(context_id, "before", execution.before, ctx, execution.git)
        run_execution_sub_tasks(execution, ctx, completed_task_ids, on_task_completed)
        run_hook_phase(context_id, "after", execution.after, ctx, execution.git)
    except PropagateError as error:
        if not execution.on_failure:
            raise
        try:
            run_hook_phase(context_id, "on_failure", execution.on_failure, ctx, execution.git)
        except PropagateError as on_failure_error:
            raise PropagateError(f"{str(error).rstrip('.')}; {on_failure_error}") from on_failure_error
        raise
    LOGGER.info("Execution '%s' completed successfully.", execution.name)
