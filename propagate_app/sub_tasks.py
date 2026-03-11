from __future__ import annotations

from typing import NoReturn
from pathlib import Path

from .constants import LOGGER
from .context_sources import run_context_source
from .errors import PropagateError
from .models import ContextSourceConfig, ExecutionConfig, RuntimeContext, SubTaskConfig
from .processes import build_agent_command, run_agent_command, run_shell_command
from .prompts import build_sub_task_prompt
from .temp_files import cleanup_temp_file, write_temp_text


def run_execution_sub_tasks(execution: ExecutionConfig, runtime_context: RuntimeContext) -> None:
    for sub_task in execution.sub_tasks:
        run_sub_task(execution.name, sub_task, runtime_context)


def run_sub_task(execution_name: str, sub_task: SubTaskConfig, runtime_context: RuntimeContext) -> None:
    LOGGER.info("Running sub-task '%s' for execution '%s' using prompt '%s'.", sub_task.task_id, execution_name, sub_task.prompt_path)
    run_sub_task_hook_phase(sub_task, "before", sub_task.before, runtime_context)
    temp_prompt_path = write_temp_text(
        build_sub_task_prompt(sub_task.prompt_path, sub_task.task_id, runtime_context.working_dir),
        prefix="propagate-",
        suffix=".md",
    )
    try:
        run_sub_task_agent(sub_task, temp_prompt_path, runtime_context)
    finally:
        cleanup_temp_file(temp_prompt_path, "temporary prompt file")
    run_sub_task_hook_phase(sub_task, "after", sub_task.after, runtime_context)
    LOGGER.info("Completed sub-task '%s' for execution '%s'.", sub_task.task_id, execution_name)


def run_sub_task_hook_phase(
    sub_task: SubTaskConfig,
    phase: str,
    actions: list[str],
    runtime_context: RuntimeContext,
) -> None:
    try:
        run_hook_phase(sub_task.task_id, phase, actions, runtime_context.context_sources, runtime_context.working_dir)
    except PropagateError as error:
        handle_sub_task_failure(sub_task, runtime_context.context_sources, runtime_context.working_dir, error)


def run_sub_task_agent(sub_task: SubTaskConfig, temp_prompt_path: Path, runtime_context: RuntimeContext) -> None:
    command = build_agent_command(runtime_context.agent_command, temp_prompt_path)
    try:
        run_agent_command(command, runtime_context.working_dir, sub_task.task_id)
    except PropagateError as error:
        handle_sub_task_failure(sub_task, runtime_context.context_sources, runtime_context.working_dir, error)


def handle_sub_task_failure(
    sub_task: SubTaskConfig,
    context_sources: dict[str, ContextSourceConfig],
    working_dir: Path,
    error: PropagateError,
) -> NoReturn:
    if not sub_task.on_failure:
        raise error
    try:
        run_hook_phase(sub_task.task_id, "on_failure", sub_task.on_failure, context_sources, working_dir)
    except PropagateError as on_failure_error:
        raise PropagateError(f"{str(error).rstrip('.')}; {on_failure_error}") from on_failure_error
    raise error


def run_hook_phase(
    task_id: str,
    phase: str,
    actions: list[str],
    context_sources: dict[str, ContextSourceConfig],
    working_dir: Path,
) -> None:
    total_actions = len(actions)
    for hook_index, action in enumerate(actions, start=1):
        if action.startswith(":"):
            source_name = action[1:]
            LOGGER.info(
                "Loading context source '%s' for %s hook %d/%d in sub-task '%s'.",
                source_name,
                phase,
                hook_index,
                total_actions,
                task_id,
            )
            run_context_source(context_sources[source_name], working_dir, task_id)
            continue
        LOGGER.info("Running %s hook %d/%d for sub-task '%s'.", phase, hook_index, total_actions, task_id)
        run_shell_command(
            action,
            working_dir,
            failure_message=build_hook_failure_message(phase, hook_index, task_id, "{exit_code}"),
            start_failure_message=f"Failed to start {phase} hook #{hook_index} for sub-task '{task_id}': {{error}}",
        )


def build_hook_failure_message(phase: str, hook_index: int, task_id: str, exit_code: int | str) -> str:
    return f"{get_hook_phase_display_name(phase)} hook #{hook_index} failed for sub-task '{task_id}' with exit code {exit_code}."


def get_hook_phase_display_name(phase: str) -> str:
    display_names = {"before": "Before", "after": "After", "on_failure": "on_failure"}
    return display_names.get(phase, phase)
