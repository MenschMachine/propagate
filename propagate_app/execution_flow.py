from collections.abc import Callable
from dataclasses import replace

from .constants import LOGGER, PHASE_AFTER, PHASE_BEFORE
from .errors import PropagateError
from .git_runtime import restore_git_run_state
from .models import ExecutionConfig, GitRunState, RuntimeContext
from .sub_tasks import run_execution_sub_tasks, run_hook_phase


def run_configured_execution(
    execution: ExecutionConfig,
    runtime_context: RuntimeContext,
    completed_task_phases: dict[str, str] | None = None,
    on_phase_completed: Callable[[str, str, str], None] | None = None,
    completed_execution_phase: str | None = None,
    on_runtime_context_updated: Callable[[RuntimeContext], None] | None = None,
) -> RuntimeContext:
    LOGGER.info("Running execution '%s' with %d sub-task(s).", execution.name, len(execution.sub_tasks))
    if execution.git and (completed_task_phases or completed_execution_phase):
        git_state = restore_git_run_state(runtime_context)
    else:
        git_state = GitRunState() if execution.git else None
    ctx = replace(runtime_context, git_state=git_state)
    context_id = f"execution '{execution.name}'"
    try:
        if completed_execution_phase in (PHASE_BEFORE, PHASE_AFTER):
            LOGGER.info("Skipping already completed execution 'before' hooks for '%s'.", execution.name)
        else:
            run_hook_phase(context_id, "before", execution.before, ctx, execution.git)
            if on_phase_completed is not None and execution.before:
                on_phase_completed(execution.name, "", PHASE_BEFORE)
        ctx = run_execution_sub_tasks(
            execution,
            ctx,
            completed_task_phases,
            on_phase_completed,
            on_runtime_context_updated,
        )
        if completed_execution_phase == PHASE_AFTER:
            LOGGER.info("Skipping already completed execution 'after' hooks for '%s'.", execution.name)
        else:
            run_hook_phase(context_id, "after", execution.after, ctx, execution.git)
            if on_phase_completed is not None and execution.after:
                on_phase_completed(execution.name, "", PHASE_AFTER)
    except PropagateError as error:
        if not execution.on_failure:
            raise
        try:
            run_hook_phase(context_id, "on_failure", execution.on_failure, ctx, execution.git)
        except PropagateError as on_failure_error:
            raise PropagateError(f"{str(error).rstrip('.')}; {on_failure_error}") from on_failure_error
        raise
    LOGGER.info("Execution '%s' completed successfully.", execution.name)
    return ctx
