from pathlib import Path

from .context_store import context_set_command
from .models import ContextSourceConfig
from .processes import run_shell_command


def run_execution_context_source(context_source: ContextSourceConfig, working_dir: Path, execution_name: str) -> str:
    return capture_and_store_context_source_output(
        context_source,
        working_dir,
        failure_message=f"Context source '{context_source.name}' failed for execution '{execution_name}' with exit code {{exit_code}}.",
        start_failure_message=f"Failed to start context source '{context_source.name}' for execution '{execution_name}': {{error}}",
    )


def run_context_source(context_source: ContextSourceConfig, working_dir: Path, task_id: str) -> None:
    capture_and_store_context_source_output(
        context_source,
        working_dir,
        failure_message=f"Context source '{context_source.name}' failed for sub-task '{task_id}' with exit code {{exit_code}}.",
        start_failure_message=f"Failed to start context source '{context_source.name}' for sub-task '{task_id}': {{error}}",
    )


def capture_and_store_context_source_output(
    context_source: ContextSourceConfig,
    working_dir: Path,
    *,
    failure_message: str,
    start_failure_message: str,
) -> str:
    output = capture_context_source_output(
        context_source.command,
        working_dir,
        failure_message=failure_message,
        start_failure_message=start_failure_message,
    )
    context_set_command(f":{context_source.name}", output, working_dir)
    return output


def capture_context_source_output(
    command: str,
    working_dir: Path,
    failure_message: str,
    start_failure_message: str,
) -> str:
    result = run_shell_command(
        command,
        working_dir,
        failure_message=failure_message,
        start_failure_message=start_failure_message,
        capture_output=True,
        text=True,
    )
    return result.stdout
