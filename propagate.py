from __future__ import annotations

import argparse
import logging
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml


LOGGER = logging.getLogger("propagate")
CONTEXT_DIR_NAME = ".propagate-context"
CONTEXT_KEY_PATTERN = re.compile(r"^:?[A-Za-z0-9][A-Za-z0-9._-]*$")


class PropagateError(Exception):
    """Raised when the CLI encounters a user-facing configuration error."""


@dataclass(frozen=True)
class AgentConfig:
    command: str


@dataclass(frozen=True)
class ContextSourceConfig:
    command: str


@dataclass(frozen=True)
class SubTaskConfig:
    task_id: str
    prompt_path: Path
    before: list[str]
    after: list[str]
    on_failure: list[str]


@dataclass(frozen=True)
class ExecutionConfig:
    name: str
    sub_tasks: list[SubTaskConfig]


@dataclass(frozen=True)
class Config:
    version: str
    agent: AgentConfig
    context_sources: dict[str, ContextSourceConfig]
    executions: dict[str, ExecutionConfig]
    config_path: Path


class SubTaskCommandError(PropagateError):
    """Raised when a hook or agent command fails during sub-task execution."""


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="propagate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run an execution from a config file.")
    run_parser.add_argument("--config", required=True, help="Path to the Propagate YAML config.")
    run_parser.add_argument("--execution", help="Execution name to run.")

    context_parser = subparsers.add_parser("context", help="Manage local context values.")
    context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)

    context_set_parser = context_subparsers.add_parser("set", help="Store a local context value.")
    context_set_parser.add_argument(
        "key",
        help="Context key to store. Keys starting with ':' are reserved by convention.",
    )
    context_set_parser.add_argument("value", help="Context value to store.")

    context_get_parser = context_subparsers.add_parser("get", help="Read a local context value.")
    context_get_parser.add_argument(
        "key",
        help="Context key to read. Keys starting with ':' are reserved by convention.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            return run_command(args.config, args.execution)
        if args.command == "context":
            if args.context_command == "set":
                return context_set_command(args.key, args.value, Path.cwd())
            if args.context_command == "get":
                return context_get_command(args.key, Path.cwd())
    except PropagateError as error:
        LOGGER.error("%s", error)
        return 1
    except KeyboardInterrupt:
        LOGGER.error("Execution interrupted.")
        return 130

    parser.error(f"Unsupported command: {args.command}")
    return 2


def run_command(config_value: str, execution_name: str | None) -> int:
    config_path = Path(config_value).expanduser()
    config = load_config(config_path)
    execution = select_execution(config, execution_name)

    LOGGER.info("Running execution '%s' with %d sub-task(s).", execution.name, len(execution.sub_tasks))
    run_execution(execution, config.agent.command, config.context_sources, Path.cwd())
    LOGGER.info("Execution '%s' completed successfully.", execution.name)
    return 0


def context_set_command(key: str, value: str, working_dir: Path) -> int:
    validated_key = validate_context_key(key)
    context_dir = get_context_dir(working_dir)
    write_context_value(context_dir, validated_key, value)
    LOGGER.info("Stored context key '%s'.", validated_key)
    return 0


def context_get_command(key: str, working_dir: Path) -> int:
    validated_key = validate_context_key(key)
    context_dir = get_context_dir(working_dir)
    value = read_context_value(context_dir, validated_key)
    sys.stdout.write(value)
    return 0


def load_config(config_path: Path) -> Config:
    if not config_path.exists():
        raise PropagateError(f"Config file does not exist: {config_path}")

    resolved_config_path = config_path.resolve()
    try:
        with resolved_config_path.open("r", encoding="utf-8") as handle:
            raw_data = yaml.safe_load(handle)
    except OSError as error:
        raise PropagateError(f"Failed to read config file {resolved_config_path}: {error}") from error
    except yaml.YAMLError as error:
        raise PropagateError(f"Failed to parse YAML config {resolved_config_path}: {error}") from error

    if not isinstance(raw_data, dict):
        raise PropagateError("Config must be a YAML mapping.")

    version = raw_data.get("version")
    if version != "3":
        raise PropagateError("Config version must be '3' for stage 3.")

    agent = parse_agent(raw_data.get("agent"))
    context_sources = parse_context_sources(raw_data.get("context_sources"))
    executions = parse_executions(raw_data.get("executions"), resolved_config_path.parent)
    validate_hook_references(executions, context_sources)

    return Config(
        version=version,
        agent=agent,
        context_sources=context_sources,
        executions=executions,
        config_path=resolved_config_path,
    )


def parse_agent(agent_data: Any) -> AgentConfig:
    if not isinstance(agent_data, dict):
        raise PropagateError("Config must include an 'agent' mapping.")

    command = agent_data.get("command")
    if not isinstance(command, str) or not command.strip():
        raise PropagateError("Config 'agent.command' must be a non-empty string.")

    if "{prompt_file}" not in command:
        raise PropagateError("Config 'agent.command' must contain the '{prompt_file}' placeholder.")

    return AgentConfig(command=command)


def parse_context_sources(context_sources_data: Any) -> dict[str, ContextSourceConfig]:
    if context_sources_data is None:
        return {}
    if not isinstance(context_sources_data, dict) or not context_sources_data:
        raise PropagateError("Config 'context_sources' must be a non-empty mapping when provided.")

    context_sources: dict[str, ContextSourceConfig] = {}
    for source_name, source_data in context_sources_data.items():
        validated_name = validate_context_source_name(source_name)
        if not isinstance(source_data, dict):
            raise PropagateError(f"Context source '{validated_name}' must be a mapping.")
        if set(source_data) != {"command"}:
            raise PropagateError(
                f"Context source '{validated_name}' must define only the 'command' field in stage 3."
            )

        command = source_data.get("command")
        if not isinstance(command, str) or not command.strip():
            raise PropagateError(f"Context source '{validated_name}' field 'command' must be a non-empty string.")

        context_sources[validated_name] = ContextSourceConfig(command=command)

    return context_sources


def parse_executions(executions_data: Any, config_dir: Path) -> dict[str, ExecutionConfig]:
    if not isinstance(executions_data, dict) or not executions_data:
        raise PropagateError("Config must include at least one execution in 'executions'.")

    executions: dict[str, ExecutionConfig] = {}
    for execution_name, execution_data in executions_data.items():
        if not isinstance(execution_name, str) or not execution_name.strip():
            raise PropagateError("Execution names must be non-empty strings.")
        executions[execution_name] = parse_execution(execution_name, execution_data, config_dir)

    return executions


def parse_execution(name: str, execution_data: Any, config_dir: Path) -> ExecutionConfig:
    if not isinstance(execution_data, dict):
        raise PropagateError(f"Execution '{name}' must be a mapping.")

    sub_tasks_data = execution_data.get("sub_tasks")
    if not isinstance(sub_tasks_data, list) or not sub_tasks_data:
        raise PropagateError(f"Execution '{name}' must define a non-empty 'sub_tasks' list.")

    sub_tasks: list[SubTaskConfig] = []
    for index, sub_task_data in enumerate(sub_tasks_data, start=1):
        if not isinstance(sub_task_data, dict):
            raise PropagateError(f"Execution '{name}' sub-task #{index} must be a mapping.")

        task_id = sub_task_data.get("id")
        prompt_value = sub_task_data.get("prompt")
        if not isinstance(task_id, str) or not task_id.strip():
            raise PropagateError(f"Execution '{name}' sub-task #{index} must include a non-empty 'id'.")
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            raise PropagateError(f"Execution '{name}' sub-task '{task_id}' must include a non-empty 'prompt'.")

        prompt_path = Path(prompt_value).expanduser()
        if not prompt_path.is_absolute():
            prompt_path = (config_dir / prompt_path).resolve()

        sub_tasks.append(
            SubTaskConfig(
                task_id=task_id,
                prompt_path=prompt_path,
                before=parse_hook_actions(sub_task_data.get("before"), name, task_id, "before"),
                after=parse_hook_actions(sub_task_data.get("after"), name, task_id, "after"),
                on_failure=parse_hook_actions(
                    sub_task_data.get("on_failure"),
                    name,
                    task_id,
                    "on_failure",
                ),
            )
        )

    return ExecutionConfig(name=name, sub_tasks=sub_tasks)


def parse_hook_actions(actions_data: Any, execution_name: str, task_id: str, phase: str) -> list[str]:
    if actions_data is None:
        return []
    if not isinstance(actions_data, list):
        raise PropagateError(
            f"Execution '{execution_name}' sub-task '{task_id}' field '{phase}' must be a list of commands."
        )

    actions: list[str] = []
    for index, action_data in enumerate(actions_data, start=1):
        if not isinstance(action_data, str) or not action_data.strip():
            raise PropagateError(
                f"Execution '{execution_name}' sub-task '{task_id}' {phase} hook #{index} must be a non-empty string."
            )
        if action_data.startswith(":"):
            validate_context_key(action_data)
        actions.append(action_data)

    return actions


def validate_context_source_name(source_name: Any) -> str:
    if not isinstance(source_name, str) or not source_name.strip():
        raise PropagateError("Context source names must be non-empty strings.")
    if source_name.startswith(":"):
        raise PropagateError(f"Context source '{source_name}' must not start with ':'.")
    return validate_context_key(source_name)


def validate_hook_references(
    executions: dict[str, ExecutionConfig],
    context_sources: dict[str, ContextSourceConfig],
) -> None:
    for execution in executions.values():
        for sub_task in execution.sub_tasks:
            for phase, actions in (
                ("before", sub_task.before),
                ("after", sub_task.after),
                ("on_failure", sub_task.on_failure),
            ):
                for index, action in enumerate(actions, start=1):
                    if not action.startswith(":"):
                        continue
                    source_name = action[1:]
                    if source_name not in context_sources:
                        raise PropagateError(
                            f"Execution '{execution.name}' sub-task '{sub_task.task_id}' "
                            f"{phase} hook #{index} references undefined context source '{source_name}'."
                        )


def select_execution(config: Config, requested_name: str | None) -> ExecutionConfig:
    if requested_name:
        try:
            return config.executions[requested_name]
        except KeyError as error:
            available = ", ".join(sorted(config.executions))
            raise PropagateError(
                f"Execution '{requested_name}' was not found. Available executions: {available}"
            ) from error

    if len(config.executions) == 1:
        return next(iter(config.executions.values()))

    available = ", ".join(sorted(config.executions))
    raise PropagateError(
        f"Config defines multiple executions; specify one with --execution. Available executions: {available}"
    )


def run_execution(
    execution: ExecutionConfig,
    agent_command: str,
    context_sources: dict[str, ContextSourceConfig],
    working_dir: Path,
) -> None:
    for sub_task in execution.sub_tasks:
        run_sub_task(sub_task, agent_command, context_sources, working_dir)


def run_sub_task(
    sub_task: SubTaskConfig,
    agent_command: str,
    context_sources: dict[str, ContextSourceConfig],
    working_dir: Path,
) -> None:
    LOGGER.info("Starting sub-task '%s' using prompt %s", sub_task.task_id, sub_task.prompt_path)
    try:
        run_hook_phase(sub_task.task_id, "before", sub_task.before, context_sources, working_dir)

        prompt_contents = read_prompt_file(sub_task.prompt_path)
        context_items = load_local_context(get_context_dir(working_dir))
        if context_items:
            LOGGER.info("Loaded %d context value(s) for sub-task '%s'.", len(context_items), sub_task.task_id)
        prompt_contents = append_context_to_prompt(prompt_contents, context_items)

        temp_prompt_path: Path | None = None
        try:
            temp_prompt_path = write_temp_prompt_file(sub_task.task_id, prompt_contents)
            command = agent_command.replace("{prompt_file}", shlex.quote(str(temp_prompt_path)))
            run_agent_command(sub_task.task_id, command, working_dir)
        finally:
            if temp_prompt_path is not None:
                remove_temp_prompt_file(temp_prompt_path)

        run_hook_phase(sub_task.task_id, "after", sub_task.after, context_sources, working_dir)
    except SubTaskCommandError as error:
        on_failure_errors = run_on_failure_hooks(sub_task.task_id, sub_task.on_failure, context_sources, working_dir)
        message = str(error)
        if on_failure_errors:
            message = f"{message} {' '.join(on_failure_errors)}"
        raise PropagateError(message) from error

    LOGGER.info("Completed sub-task '%s'.", sub_task.task_id)


def run_agent_command(task_id: str, command: str, working_dir: Path) -> None:
    LOGGER.info("Running agent command for sub-task '%s'.", task_id)
    try:
        subprocess.run(command, shell=True, cwd=working_dir, check=True)
    except OSError as error:
        raise SubTaskCommandError(f"Failed to execute agent command for sub-task '{task_id}': {error}") from error
    except subprocess.CalledProcessError as error:
        raise SubTaskCommandError(
            f"Agent command failed for sub-task '{task_id}' with exit code {error.returncode}."
        ) from error


def run_hook_phase(
    task_id: str,
    phase: str,
    actions: list[str],
    context_sources: dict[str, ContextSourceConfig],
    working_dir: Path,
) -> None:
    if not actions:
        return

    LOGGER.info("Starting %s hook phase for sub-task '%s'.", phase, task_id)
    total_actions = len(actions)
    for index, action in enumerate(actions, start=1):
        run_hook_action(task_id, phase, index, total_actions, action, context_sources, working_dir)


def run_hook_action(
    task_id: str,
    phase: str,
    index: int,
    total_actions: int,
    action: str,
    context_sources: dict[str, ContextSourceConfig],
    working_dir: Path,
) -> None:
    LOGGER.info("Running %s hook %d/%d for sub-task '%s'.", phase, index, total_actions, task_id)
    if action.startswith(":"):
        run_context_source(task_id, action[1:], context_sources, working_dir)
        return

    try:
        subprocess.run(action, shell=True, cwd=working_dir, check=True)
    except OSError as error:
        raise SubTaskCommandError(
            f"Failed to execute {phase} hook #{index} for sub-task '{task_id}': {error}"
        ) from error
    except subprocess.CalledProcessError as error:
        raise SubTaskCommandError(format_hook_failure_message(phase, index, task_id, error.returncode)) from error


def run_context_source(
    task_id: str,
    source_name: str,
    context_sources: dict[str, ContextSourceConfig],
    working_dir: Path,
) -> None:
    try:
        context_source = context_sources[source_name]
    except KeyError as error:
        raise PropagateError(f"Sub-task '{task_id}' references undefined context source '{source_name}'.") from error

    LOGGER.info("Loading context source '%s' for sub-task '%s'.", source_name, task_id)
    try:
        result = subprocess.run(
            context_source.command,
            shell=True,
            cwd=working_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise SubTaskCommandError(
            f"Failed to execute context source '{source_name}' for sub-task '{task_id}': {error}"
        ) from error
    except subprocess.CalledProcessError as error:
        raise SubTaskCommandError(
            f"Context source '{source_name}' failed for sub-task '{task_id}' with exit code {error.returncode}."
        ) from error

    write_context_value(get_context_dir(working_dir), f":{source_name}", result.stdout)


def run_on_failure_hooks(
    task_id: str,
    actions: list[str],
    context_sources: dict[str, ContextSourceConfig],
    working_dir: Path,
) -> list[str]:
    if not actions:
        return []

    LOGGER.info("Starting on_failure hook phase for sub-task '%s'.", task_id)
    failures: list[str] = []
    total_actions = len(actions)
    for index, action in enumerate(actions, start=1):
        try:
            run_hook_action(task_id, "on_failure", index, total_actions, action, context_sources, working_dir)
        except SubTaskCommandError as error:
            failures.append(str(error))

    return failures


def format_hook_failure_message(phase: str, index: int, task_id: str, return_code: int) -> str:
    phase_names = {
        "before": "Before",
        "after": "After",
        "on_failure": "on_failure",
    }
    return f"{phase_names[phase]} hook #{index} failed for sub-task '{task_id}' with exit code {return_code}."


def read_prompt_file(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise PropagateError(f"Prompt file does not exist: {prompt_path}")

    try:
        return prompt_path.read_text(encoding="utf-8")
    except OSError as error:
        raise PropagateError(f"Failed to read prompt file {prompt_path}: {error}") from error


def write_temp_prompt_file(task_id: str, prompt_contents: str) -> Path:
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f"propagate-{task_id}-",
            suffix=".md",
            delete=False,
        ) as handle:
            handle.write(prompt_contents)
            return Path(handle.name)
    except OSError as error:
        raise PropagateError(f"Failed to create temporary prompt file for sub-task '{task_id}': {error}") from error


def remove_temp_prompt_file(temp_prompt_path: Path) -> None:
    try:
        temp_prompt_path.unlink(missing_ok=True)
    except OSError as error:
        LOGGER.warning("Failed to remove temporary prompt file %s: %s", temp_prompt_path, error)


def get_context_dir(working_dir: Path) -> Path:
    return working_dir / CONTEXT_DIR_NAME


def validate_context_key(key: str) -> str:
    if not key:
        raise PropagateError("Context key must not be empty.")
    if "/" in key or "\\" in key:
        raise PropagateError(f"Context key '{key}' must not contain path separators.")
    if key in {".", ".."}:
        raise PropagateError(f"Context key '{key}' is not allowed.")
    if any(character.isspace() for character in key):
        raise PropagateError(f"Context key '{key}' must not contain whitespace.")
    if not CONTEXT_KEY_PATTERN.fullmatch(key):
        raise PropagateError(
            f"Context key '{key}' is invalid. Use letters, numbers, '.', '_', '-', and an optional leading ':'."
        )
    return key


def write_context_value(context_dir: Path, key: str, value: str) -> None:
    try:
        context_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PropagateError(f"Failed to create context directory {context_dir}: {error}") from error

    target_path = context_dir / key
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=context_dir,
            prefix=f".{key}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(value)
            temp_path = Path(handle.name)

        temp_path.replace(target_path)
    except OSError as error:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                LOGGER.warning("Failed to remove temporary context file %s: %s", temp_path, cleanup_error)
        raise PropagateError(f"Failed to write context key '{key}' in {context_dir}: {error}") from error


def read_context_value(context_dir: Path, key: str) -> str:
    target_path = context_dir / key
    if not target_path.exists():
        raise PropagateError(f"Context key '{key}' was not found in {context_dir}.")
    if not target_path.is_file():
        raise PropagateError(f"Context key '{key}' in {context_dir} is not a regular file.")

    try:
        return target_path.read_text(encoding="utf-8")
    except OSError as error:
        raise PropagateError(f"Failed to read context key '{key}' from {target_path}: {error}") from error


def load_local_context(context_dir: Path) -> list[tuple[str, str]]:
    if not context_dir.exists():
        return []
    if not context_dir.is_dir():
        raise PropagateError(f"Context path exists but is not a directory: {context_dir}")

    items: list[tuple[str, str]] = []
    try:
        entries = sorted(context_dir.iterdir(), key=lambda path: path.name)
    except OSError as error:
        raise PropagateError(f"Failed to read context directory {context_dir}: {error}") from error

    for entry in entries:
        if not entry.is_file():
            LOGGER.warning("Ignoring non-file context entry %s", entry)
            continue
        if entry.name.startswith(".") and entry.name.endswith(".tmp"):
            LOGGER.warning("Ignoring temporary context entry %s", entry)
            continue

        validate_context_key(entry.name)
        try:
            items.append((entry.name, entry.read_text(encoding="utf-8")))
        except OSError as error:
            raise PropagateError(f"Failed to read context key '{entry.name}' from {entry}: {error}") from error

    return items


def render_context_section(items: list[tuple[str, str]]) -> str:
    entries: list[str] = []
    for key, value in items:
        entry = f"### {key}\n{value}"
        if not entry.endswith("\n"):
            entry += "\n"
        entries.append(entry)

    joined_entries = "\n".join(entries)
    return f"## Context\n\n{joined_entries}"


def append_context_to_prompt(prompt_contents: str, items: list[tuple[str, str]]) -> str:
    if not items:
        return prompt_contents

    context_section = render_context_section(items)
    if prompt_contents.endswith("\n\n"):
        return f"{prompt_contents}{context_section}"
    if prompt_contents.endswith("\n"):
        return f"{prompt_contents}\n{context_section}"
    return f"{prompt_contents}\n\n{context_section}"


if __name__ == "__main__":
    sys.exit(main())
