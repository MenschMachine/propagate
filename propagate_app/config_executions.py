from __future__ import annotations

from pathlib import Path
from typing import Any

from .config_git import parse_git_config
from .errors import PropagateError
from .models import ExecutionConfig, SubTaskConfig
from .validation import validate_allowed_keys, validate_context_key, validate_context_source_name


def parse_executions(
    executions_data: Any,
    config_dir: Path,
    repository_names: set[str],
    context_source_names: set[str],
    signal_names: set[str],
) -> dict[str, ExecutionConfig]:
    if not isinstance(executions_data, dict) or not executions_data:
        raise PropagateError("Config must include at least one execution in 'executions'.")
    execution_names = set(executions_data)
    return {
        execution_name: parse_execution(
            execution_name,
            execution_data,
            config_dir,
            repository_names,
            execution_names,
            context_source_names,
            signal_names,
        )
        for execution_name, execution_data in executions_data.items()
    }


def parse_execution(
    name: str,
    execution_data: Any,
    config_dir: Path,
    repository_names: set[str],
    execution_names: set[str],
    context_source_names: set[str],
    signal_names: set[str],
) -> ExecutionConfig:
    if not isinstance(execution_data, dict):
        raise PropagateError(f"Execution '{name}' must be a mapping.")
    validate_allowed_keys(execution_data, {"repository", "depends_on", "sub_tasks", "git", "signals"}, f"Execution '{name}'")
    sub_tasks_data = execution_data.get("sub_tasks")
    if not isinstance(sub_tasks_data, list) or not sub_tasks_data:
        raise PropagateError(f"Execution '{name}' must define a non-empty 'sub_tasks' list.")
    sub_tasks: list[SubTaskConfig] = []
    seen_task_ids: set[str] = set()
    for index, sub_task_data in enumerate(sub_tasks_data, start=1):
        sub_task = parse_sub_task(name, index, sub_task_data, config_dir, context_source_names)
        if sub_task.task_id in seen_task_ids:
            raise PropagateError(f"Execution '{name}' contains duplicate sub-task id '{sub_task.task_id}'.")
        seen_task_ids.add(sub_task.task_id)
        sub_tasks.append(sub_task)
    return ExecutionConfig(
        name=name,
        repository=parse_execution_repository(name, execution_data.get("repository"), repository_names),
        depends_on=parse_execution_dependencies(name, execution_data.get("depends_on"), execution_names),
        signals=parse_execution_signals(name, execution_data.get("signals"), signal_names),
        sub_tasks=sub_tasks,
        git=parse_git_config(name, execution_data.get("git"), context_source_names),
    )


def parse_execution_repository(execution_name: str, repository_value: Any, repository_names: set[str]) -> str:
    if repository_value is None:
        raise PropagateError(f"Execution '{execution_name}' must declare a 'repository'.")
    if not isinstance(repository_value, str) or not repository_value.strip():
        raise PropagateError(f"Execution '{execution_name}' repository must be a non-empty string.")
    if repository_value not in repository_names:
        raise PropagateError(f"Execution '{execution_name}' references unknown repository '{repository_value}'.")
    return repository_value


def parse_execution_dependencies(execution_name: str, depends_on_data: Any, execution_names: set[str]) -> list[str]:
    if depends_on_data is None:
        return []
    if not isinstance(depends_on_data, list) or not depends_on_data:
        raise PropagateError(f"Execution '{execution_name}' depends_on must be a non-empty list when provided.")
    dependencies: list[str] = []
    seen_dependencies: set[str] = set()
    for dependency_name in depends_on_data:
        if not isinstance(dependency_name, str) or not dependency_name.strip():
            raise PropagateError(f"Execution '{execution_name}' depends_on entries must be non-empty strings.")
        if dependency_name == execution_name:
            raise PropagateError(f"Execution '{execution_name}' cannot depend on itself.")
        if dependency_name not in execution_names:
            raise PropagateError(f"Execution '{execution_name}' depends_on references unknown execution '{dependency_name}'.")
        if dependency_name in seen_dependencies:
            raise PropagateError(f"Execution '{execution_name}' depends_on declares duplicate execution '{dependency_name}'.")
        seen_dependencies.add(dependency_name)
        dependencies.append(dependency_name)
    return dependencies


def parse_execution_signals(execution_name: str, signals_data: Any, signal_names: set[str]) -> list[str]:
    if signals_data is None:
        return []
    if not isinstance(signals_data, list) or not signals_data:
        raise PropagateError(f"Execution '{execution_name}' signals must be a non-empty list when provided.")
    resolved_signals: list[str] = []
    seen_signals: set[str] = set()
    for signal_name in signals_data:
        validated_name = validate_context_source_name(signal_name)
        if validated_name not in signal_names:
            raise PropagateError(f"Execution '{execution_name}' references unknown signal '{validated_name}'.")
        if validated_name in seen_signals:
            raise PropagateError(f"Execution '{execution_name}' declares duplicate signal '{validated_name}'.")
        seen_signals.add(validated_name)
        resolved_signals.append(validated_name)
    return resolved_signals


def parse_sub_task(
    name: str,
    index: int,
    sub_task_data: Any,
    config_dir: Path,
    context_source_names: set[str],
) -> SubTaskConfig:
    if not isinstance(sub_task_data, dict):
        raise PropagateError(f"Execution '{name}' sub-task #{index} must be a mapping.")
    location = f"Execution '{name}' sub-task #{index}"
    validate_allowed_keys(sub_task_data, {"id", "prompt", "before", "after", "on_failure"}, location)
    task_id = sub_task_data.get("id")
    prompt_value = sub_task_data.get("prompt")
    if not isinstance(task_id, str) or not task_id.strip():
        raise PropagateError(f"Execution '{name}' sub-task #{index} must include a non-empty 'id'.")
    if not isinstance(prompt_value, str) or not prompt_value.strip():
        raise PropagateError(f"Execution '{name}' sub-task '{task_id}' must include a non-empty 'prompt'.")
    return SubTaskConfig(
        task_id=task_id,
        prompt_path=resolve_prompt_path(prompt_value, config_dir),
        before=parse_hook_actions(sub_task_data.get("before"), location, "before", context_source_names),
        after=parse_hook_actions(sub_task_data.get("after"), location, "after", context_source_names),
        on_failure=parse_hook_actions(sub_task_data.get("on_failure"), location, "on_failure", context_source_names),
    )


def parse_hook_actions(hook_data: Any, location: str, phase: str, context_source_names: set[str]) -> list[str]:
    if hook_data is None:
        return []
    if not isinstance(hook_data, list):
        raise PropagateError(f"{location} '{phase}' must be a list of non-empty strings.")
    actions: list[str] = []
    for hook_index, action in enumerate(hook_data, start=1):
        if not isinstance(action, str) or not action.strip():
            raise PropagateError(f"{location} '{phase}' hook #{hook_index} must be a non-empty string.")
        if action.startswith(":"):
            validate_context_key(action)
            source_name = action[1:]
            if source_name not in context_source_names:
                raise PropagateError(f"{location} '{phase}' hook #{hook_index} references unknown context source '{source_name}'.")
        actions.append(action)
    return actions


def resolve_prompt_path(prompt_value: str, config_dir: Path) -> Path:
    prompt_path = Path(prompt_value).expanduser()
    if prompt_path.is_absolute():
        return prompt_path
    return (config_dir / prompt_path).resolve()
