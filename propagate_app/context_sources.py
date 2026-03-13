from pathlib import Path

from .context_store import context_set_command, resolve_execution_context_dir
from .models import ContextSourceConfig, RuntimeContext
from .processes import run_shell_command


def run_context_source(context_source: ContextSourceConfig, runtime_context: RuntimeContext, label: str) -> str:
    context_dir = resolve_execution_context_dir(runtime_context)
    return capture_and_store_context_source_output(
        context_source,
        runtime_context.working_dir,
        context_dir,
        failure_message=f"Context source '{context_source.name}' failed for {label} with exit code {{exit_code}}.",
        start_failure_message=f"Failed to start context source '{context_source.name}' for {label}: {{error}}",
    )


def capture_and_store_context_source_output(
    context_source: ContextSourceConfig,
    working_dir: Path,
    context_dir: Path,
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
    context_set_command(f":{context_source.name}", output, context_dir)
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
    return result.stdout.strip()
