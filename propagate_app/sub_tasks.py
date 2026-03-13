from __future__ import annotations

from dataclasses import replace
from typing import NoReturn
from pathlib import Path

from .constants import ENV_CONTEXT_ROOT, ENV_EXECUTION, ENV_TASK, LOGGER
from .context_sources import run_context_source
from .errors import PropagateError
from typing import Callable

from .models import ExecutionConfig, RuntimeContext, SubTaskConfig
from .processes import build_agent_command, run_agent_command, run_shell_command
from .prompts import build_sub_task_prompt
from .temp_files import cleanup_temp_file, write_temp_text


def build_context_env(runtime_context: RuntimeContext) -> dict[str, str]:
    env: dict[str, str] = {}
    env[ENV_CONTEXT_ROOT] = str(runtime_context.context_root)
    if runtime_context.execution_name:
        env[ENV_EXECUTION] = runtime_context.execution_name
    env[ENV_TASK] = runtime_context.task_id
    return env


def run_execution_sub_tasks(
    execution: ExecutionConfig,
    runtime_context: RuntimeContext,
    completed_task_ids: set[str] | None = None,
    on_task_completed: Callable[[str, str], None] | None = None,
) -> None:
    for sub_task in execution.sub_tasks:
        if completed_task_ids and sub_task.task_id in completed_task_ids:
            LOGGER.info("Skipping already completed sub-task '%s' for execution '%s'.", sub_task.task_id, execution.name)
            continue
        run_sub_task(execution.name, sub_task, runtime_context)
        if on_task_completed is not None:
            on_task_completed(execution.name, sub_task.task_id)


def run_sub_task(execution_name: str, sub_task: SubTaskConfig, runtime_context: RuntimeContext) -> None:
    LOGGER.info("Running sub-task '%s' for execution '%s'.", sub_task.task_id, execution_name)
    task_runtime_context = replace(runtime_context, task_id=sub_task.task_id)
    run_sub_task_hook_phase(sub_task, "before", sub_task.before, task_runtime_context)
    if sub_task.prompt_path is not None:
        temp_prompt_path = write_temp_text(
            build_sub_task_prompt(sub_task.prompt_path, sub_task.task_id, task_runtime_context),
            prefix="propagate-",
            suffix=".md",
        )
        try:
            run_sub_task_agent(sub_task, temp_prompt_path, task_runtime_context)
        finally:
            cleanup_temp_file(temp_prompt_path, "temporary prompt file")
    else:
        LOGGER.debug("Sub-task '%s' has no prompt, skipping agent invocation.", sub_task.task_id)
    run_sub_task_hook_phase(sub_task, "after", sub_task.after, task_runtime_context)
    LOGGER.info("Completed sub-task '%s' for execution '%s'.", sub_task.task_id, execution_name)


def run_sub_task_hook_phase(
    sub_task: SubTaskConfig,
    phase: str,
    actions: list[str],
    runtime_context: RuntimeContext,
) -> None:
    try:
        run_hook_phase(sub_task.task_id, phase, actions, runtime_context)
    except PropagateError as error:
        handle_sub_task_failure(sub_task, runtime_context, error)


def run_sub_task_agent(sub_task: SubTaskConfig, temp_prompt_path: Path, runtime_context: RuntimeContext) -> None:
    command = build_agent_command(runtime_context.agent_command, temp_prompt_path)
    extra_env = build_context_env(runtime_context)
    try:
        run_agent_command(command, runtime_context.working_dir, sub_task.task_id, extra_env=extra_env)
    except PropagateError as error:
        handle_sub_task_failure(sub_task, runtime_context, error)


def handle_sub_task_failure(
    sub_task: SubTaskConfig,
    runtime_context: RuntimeContext,
    error: PropagateError,
) -> NoReturn:
    if not sub_task.on_failure:
        raise error
    try:
        run_hook_phase(sub_task.task_id, "on_failure", sub_task.on_failure, runtime_context)
    except PropagateError as on_failure_error:
        raise PropagateError(f"{str(error).rstrip('.')}; {on_failure_error}") from on_failure_error
    raise error


def run_hook_phase(
    task_id: str,
    phase: str,
    actions: list[str],
    runtime_context: RuntimeContext,
) -> None:
    extra_env = build_context_env(runtime_context)
    total_actions = len(actions)
    for hook_index, action in enumerate(actions, start=1):
        if action.startswith(":"):
            source_name = action[1:]
            LOGGER.info(
                "Evaluating context source '%s' for %s hook %d/%d in sub-task '%s'.",
                source_name,
                phase,
                hook_index,
                total_actions,
                task_id,
            )
            run_context_source(runtime_context.context_sources[source_name], runtime_context, f"sub-task '{task_id}'")
            continue
        LOGGER.info("Running %s hook %d/%d for sub-task '%s'.", phase, hook_index, total_actions, task_id)
        run_shell_command(
            action,
            runtime_context.working_dir,
            failure_message=build_hook_failure_message(phase, hook_index, task_id, "{exit_code}"),
            start_failure_message=f"Failed to start {phase} hook #{hook_index} for sub-task '{task_id}': {{error}}",
            extra_env=extra_env,
        )


def build_hook_failure_message(phase: str, hook_index: int, task_id: str, exit_code: int | str) -> str:
    return f"{get_hook_phase_display_name(phase)} hook #{hook_index} failed for sub-task '{task_id}' with exit code {exit_code}."


def get_hook_phase_display_name(phase: str) -> str:
    display_names = {"before": "Before", "after": "After", "on_failure": "on_failure"}
    return display_names.get(phase, phase)
