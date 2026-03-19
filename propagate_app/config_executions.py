from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config_git import parse_git_config
from .constants import LOGGER
from .errors import PropagateError
from .models import ExecutionConfig, ExecutionSignalConfig, SignalConfig, SubTaskConfig, SubTaskRouteConfig
from .signals import validate_signal_when_clause
from .validation import validate_allowed_keys, validate_context_key, validate_context_source_name


def resolve_execution_includes(executions_data: dict, config_dir: Path) -> dict:
    """Pop 'include' key, load referenced files, merge with inline executions.

    Inline executions take precedence over included ones. Duplicates between
    include files still raise an error.
    """
    inline = dict(executions_data)
    include = inline.pop("include", None)
    if include is None:
        return inline
    paths = [include] if isinstance(include, str) else include
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise PropagateError("executions.include must be a string or list of strings.")
    all_included: dict = {}
    for path_str in paths:
        file_path = (config_dir / path_str).resolve()
        if not file_path.exists():
            raise PropagateError(f"Execution include file does not exist: {file_path}")
        LOGGER.debug("Loading execution include: %s", file_path)
        try:
            with file_path.open("r", encoding="utf-8") as handle:
                included = yaml.safe_load(handle)
        except yaml.YAMLError as error:
            raise PropagateError(
                f"Failed to parse execution include file {file_path}: {error}"
            ) from error
        if not isinstance(included, dict):
            raise PropagateError(
                f"Execution include file must be a YAML mapping: {file_path}"
            )
        for key in included:
            if key in all_included:
                raise PropagateError(
                    f"Duplicate execution '{key}' from include file {file_path}"
                )
        all_included.update(included)
    for key in inline:
        if key in all_included:
            LOGGER.debug("Inline execution '%s' overrides included definition", key)
    merged = {**all_included, **inline}
    return merged


def parse_executions(
    executions_data: Any,
    config_dir: Path,
    repository_names: set[str],
    context_source_names: set[str],
    signal_configs: dict[str, SignalConfig],
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
            signal_configs,
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
    signal_configs: dict[str, SignalConfig],
) -> ExecutionConfig:
    if not isinstance(execution_data, dict):
        raise PropagateError(f"Execution '{name}' must be a mapping.")
    validate_allowed_keys(execution_data, {"repository", "depends_on", "sub_tasks", "git", "signals", "before", "after", "on_failure"}, f"Execution '{name}'")
    sub_tasks_data = execution_data.get("sub_tasks")
    if not isinstance(sub_tasks_data, list) or not sub_tasks_data:
        raise PropagateError(f"Execution '{name}' must define a non-empty 'sub_tasks' list.")
    sub_tasks: list[SubTaskConfig] = []
    seen_task_ids: set[str] = set()
    for index, sub_task_data in enumerate(sub_tasks_data, start=1):
        sub_task = parse_sub_task(name, index, sub_task_data, config_dir, context_source_names, signal_configs, seen_task_ids)
        if sub_task.task_id in seen_task_ids:
            raise PropagateError(f"Execution '{name}' contains duplicate sub-task id '{sub_task.task_id}'.")
        seen_task_ids.add(sub_task.task_id)
        sub_tasks.append(sub_task)
    location = f"Execution '{name}'"
    return ExecutionConfig(
        name=name,
        repository=parse_execution_repository(name, execution_data.get("repository"), repository_names),
        depends_on=parse_execution_dependencies(name, execution_data.get("depends_on"), execution_names),
        signals=parse_execution_signals(name, execution_data.get("signals"), signal_configs),
        sub_tasks=sub_tasks,
        git=parse_git_config(name, execution_data.get("git"), context_source_names),
        before=parse_hook_actions(execution_data.get("before"), location, "before", context_source_names),
        after=parse_hook_actions(execution_data.get("after"), location, "after", context_source_names),
        on_failure=parse_hook_actions(execution_data.get("on_failure"), location, "on_failure", context_source_names),
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


def parse_execution_signals(
    execution_name: str,
    signals_data: Any,
    signal_configs: dict[str, SignalConfig],
) -> list[ExecutionSignalConfig]:
    if signals_data is None:
        return []
    if not isinstance(signals_data, list) or not signals_data:
        raise PropagateError(f"Execution '{execution_name}' signals must be a non-empty list when provided.")
    resolved_signals: list[ExecutionSignalConfig] = []
    seen_signals: set[str] = set()
    for index, entry in enumerate(signals_data, start=1):
        location = f"Execution '{execution_name}' signal #{index}"
        if isinstance(entry, str):
            validated_name = validate_context_source_name(entry)
            when = None
        elif isinstance(entry, dict):
            validate_allowed_keys(entry, {"signal", "when"}, location)
            raw_name = entry.get("signal")
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise PropagateError(f"{location} must include a non-empty 'signal' key.")
            validated_name = validate_context_source_name(raw_name)
            when = entry.get("when")
            if when is not None and not isinstance(when, dict):
                raise PropagateError(f"{location} 'when' must be a mapping when provided.")
            if isinstance(when, dict) and not when:
                LOGGER.debug("%s has an empty 'when' clause — it matches any payload, same as omitting 'when'.", location)
        else:
            raise PropagateError(f"{location} must be a string or a mapping.")
        if validated_name not in signal_configs:
            raise PropagateError(f"Execution '{execution_name}' references unknown signal '{validated_name}'.")
        if when:
            _validate_when_keys(when, signal_configs[validated_name], location)
        if validated_name in seen_signals:
            raise PropagateError(f"Execution '{execution_name}' declares duplicate signal '{validated_name}'.")
        seen_signals.add(validated_name)
        resolved_signals.append(ExecutionSignalConfig(signal_name=validated_name, when=when))
    return resolved_signals


def _validate_when_keys(when: dict[str, Any], signal_config: SignalConfig, location: str) -> None:
    validate_signal_when_clause(when, signal_config, location, "'when'")


def parse_sub_task(
    name: str,
    index: int,
    sub_task_data: Any,
    config_dir: Path,
    context_source_names: set[str],
    signal_configs: dict[str, SignalConfig] | None = None,
    seen_task_ids: set[str] | None = None,
) -> SubTaskConfig:
    if not isinstance(sub_task_data, dict):
        raise PropagateError(f"Execution '{name}' sub-task #{index} must be a mapping.")
    location = f"Execution '{name}' sub-task #{index}"
    validate_allowed_keys(sub_task_data, {"id", "prompt", "before", "after", "on_failure", "when", "wait_for_signal", "routes"}, location)
    task_id = sub_task_data.get("id")
    prompt_value = sub_task_data.get("prompt")
    if not isinstance(task_id, str) or not task_id.strip():
        raise PropagateError(f"Execution '{name}' sub-task #{index} must include a non-empty 'id'.")
    if prompt_value is not None and (not isinstance(prompt_value, str) or not prompt_value.strip()):
        raise PropagateError(f"Execution '{name}' sub-task '{task_id}' 'prompt' must be a non-empty string when provided.")
    prompt_path = resolve_prompt_path(prompt_value, config_dir) if prompt_value else None
    when_value = parse_when_condition(sub_task_data.get("when"), location)
    wait_for_signal = sub_task_data.get("wait_for_signal")
    routes_data = sub_task_data.get("routes")
    routes: list[SubTaskRouteConfig] = []
    if wait_for_signal is not None or routes_data is not None:
        if wait_for_signal is None or routes_data is None:
            raise PropagateError(f"{location} 'wait_for_signal' and 'routes' must both be present together.")
        if not isinstance(wait_for_signal, str) or not wait_for_signal.strip():
            raise PropagateError(f"{location} 'wait_for_signal' must be a non-empty string.")
        if signal_configs is not None and wait_for_signal not in signal_configs:
            raise PropagateError(f"{location} 'wait_for_signal' references unknown signal '{wait_for_signal}'.")
        if prompt_path is not None:
            raise PropagateError(f"{location} with 'wait_for_signal' must not have 'prompt'.")
        if sub_task_data.get("on_failure"):
            raise PropagateError(f"{location} with 'wait_for_signal' must not have 'on_failure' hooks.")
        routes = parse_routes(routes_data, location, seen_task_ids, signal_configs[wait_for_signal] if signal_configs is not None else None)
    return SubTaskConfig(
        task_id=task_id,
        prompt_path=prompt_path,
        before=parse_hook_actions(sub_task_data.get("before"), location, "before", context_source_names),
        after=parse_hook_actions(sub_task_data.get("after"), location, "after", context_source_names),
        on_failure=parse_hook_actions(sub_task_data.get("on_failure"), location, "on_failure", context_source_names),
        when=when_value,
        wait_for_signal=wait_for_signal,
        routes=routes,
    )


def parse_routes(
    routes_data: Any,
    location: str,
    seen_task_ids: set[str] | None,
    signal_config: SignalConfig | None,
) -> list[SubTaskRouteConfig]:
    if not isinstance(routes_data, list) or not routes_data:
        raise PropagateError(f"{location} 'routes' must be a non-empty list.")
    routes: list[SubTaskRouteConfig] = []
    for route_index, route_data in enumerate(routes_data, start=1):
        route_location = f"{location} route #{route_index}"
        if not isinstance(route_data, dict):
            raise PropagateError(f"{route_location} must be a mapping.")
        validate_allowed_keys(route_data, {"when", "goto", "continue"}, route_location)
        when = route_data.get("when")
        if not isinstance(when, dict) or not when:
            raise PropagateError(f"{route_location} 'when' must be a non-empty mapping.")
        if signal_config is not None:
            validate_signal_when_clause(when, signal_config, route_location, "'when'")
        goto = route_data.get("goto")
        continue_flow = route_data.get("continue", False)
        if goto is not None and continue_flow:
            raise PropagateError(f"{route_location} must have exactly one of 'goto' or 'continue', not both.")
        if goto is None and not continue_flow:
            raise PropagateError(f"{route_location} must have exactly one of 'goto' or 'continue'.")
        if goto is not None:
            if not isinstance(goto, str) or not goto.strip():
                raise PropagateError(f"{route_location} 'goto' must be a non-empty string.")
            if seen_task_ids is not None and goto not in seen_task_ids:
                raise PropagateError(f"{route_location} 'goto' references unknown sub-task '{goto}'.")
        if not isinstance(continue_flow, bool):
            raise PropagateError(f"{route_location} 'continue' must be a boolean.")
        routes.append(SubTaskRouteConfig(when=when, goto=goto, continue_flow=continue_flow))
    return routes


_KNOWN_GIT_HOOK_COMMANDS = {"branch", "commit", "push", "pr", "publish",
    "pr-labels-add", "pr-labels-remove", "pr-labels-list",
    "pr-comment-add", "pr-comments-list", "pr-checks-wait"}

_GIT_COMMANDS_REQUIRING_ARGS = {"pr-labels-add", "pr-labels-remove"}
_GIT_COMMANDS_SINGLE_KEY_ARG = {"pr-labels-list", "pr-comment-add", "pr-comments-list"}


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
        elif action.startswith("git:"):
            parts = action[4:].split()
            git_command = parts[0]
            args = parts[1:]
            if git_command not in _KNOWN_GIT_HOOK_COMMANDS:
                raise PropagateError(
                    f"{location} '{phase}' hook #{hook_index} uses unknown git command '{action}'."
                    f" Known commands: {', '.join(sorted(_KNOWN_GIT_HOOK_COMMANDS))}."
                )
            if git_command in _GIT_COMMANDS_REQUIRING_ARGS:
                if not args:
                    raise PropagateError(
                        f"{location} '{phase}' hook #{hook_index} 'git:{git_command}' requires at least one label argument."
                    )
                for arg in args:
                    if not arg:
                        raise PropagateError(
                            f"{location} '{phase}' hook #{hook_index} 'git:{git_command}' arguments must be non-empty."
                        )
            elif git_command in _GIT_COMMANDS_SINGLE_KEY_ARG:
                if len(args) != 1:
                    raise PropagateError(
                        f"{location} '{phase}' hook #{hook_index} 'git:{git_command}' requires exactly one argument."
                    )
                if not args[0].startswith(":"):
                    raise PropagateError(
                        f"{location} '{phase}' hook #{hook_index} 'git:{git_command}' argument must be a ':'-prefixed context key."
                    )
            elif git_command == "pr-checks-wait":
                if len(args) < 2 or not args[0].startswith(":") or not args[1].startswith(":"):
                    raise PropagateError(
                        f"{location} '{phase}' hook #{hook_index} 'git:pr-checks-wait' requires two ':'-prefixed context key arguments (result key, status key)."
                    )
                if len(args) > 4:
                    raise PropagateError(
                        f"{location} '{phase}' hook #{hook_index} 'git:pr-checks-wait' accepts at most 4 arguments (result key, status key, interval, timeout)."
                    )
                for extra_arg in args[2:]:
                    if not extra_arg.isdigit() or int(extra_arg) <= 0:
                        raise PropagateError(
                            f"{location} '{phase}' hook #{hook_index} 'git:pr-checks-wait' interval and timeout must be positive integers."
                        )
        actions.append(action)
    return actions


def parse_when_condition(when_value: Any, location: str) -> str | None:
    if when_value is None:
        return None
    if not isinstance(when_value, str) or not when_value.strip():
        raise PropagateError(f"{location} 'when' must be a non-empty string when provided.")
    stripped = when_value.strip()
    if stripped.startswith("!:"):
        key_part = stripped[1:]
    elif stripped.startswith(":"):
        key_part = stripped
    else:
        raise PropagateError(f"{location} 'when' must be a ':key' or '!:key' context reference.")
    validate_context_key(key_part)
    return stripped


def resolve_prompt_path(prompt_value: str, config_dir: Path) -> Path:
    prompt_path = Path(prompt_value).expanduser()
    if prompt_path.is_absolute():
        return prompt_path
    return (config_dir / prompt_path).resolve()
