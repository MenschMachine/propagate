from .constants import LOGGER
from .git_runtime import run_execution_with_git
from .models import ExecutionConfig, RuntimeContext
from .sub_tasks import run_execution_sub_tasks


def run_configured_execution(execution: ExecutionConfig, runtime_context: RuntimeContext) -> None:
    LOGGER.info("Running execution '%s' with %d sub-task(s).", execution.name, len(execution.sub_tasks))
    if execution.git is None:
        run_execution_sub_tasks(execution, runtime_context)
    else:
        run_execution_with_git(execution, runtime_context)
    LOGGER.info("Execution '%s' completed successfully.", execution.name)
