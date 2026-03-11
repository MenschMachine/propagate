# Stage 2 Design Task

You are working inside the Propagate repository. The current runtime is stage 1. Your job in this sub-task is to design stage 2: add a local context bag to `propagate.py` while preserving all stage 1 behavior.

## Deliverables for this design sub-task

1. Write a concise design note at `docs/context-bag-stage-2-design.md`.
2. The design note must be implementation-ready for the next sub-task.
3. Do not implement the code yet unless a tiny clarification edit is unavoidable.

## Stage 2 scope

Stage 2 adds exactly these capabilities:

- `propagate context set <key> <value>`
- `propagate context get <key>`
- Context is stored as files under `.propagate-context/<key>`
- During `propagate run`, all local context values are appended to the prompt contents before the temporary prompt file is written and passed to the configured agent command
- The appended section must be deterministic and clearly labeled as `Context`

Stage 2 still does not include hooks, git operations, signals, propagation, `includes`, `defaults`, or guidelines.

## Required design decisions

Your design note must explicitly define:

1. CLI shape and argument parsing changes.
2. Where the context directory lives. Use the invocation working directory so the store is local to the repo being operated on.
3. How keys are validated. Prevent path traversal and unsafe filenames while preserving future compatibility for reserved `:`-prefixed keys that stage 3 will use with `propagate context set :source-name`.
4. How `context set` writes values and what happens on overwrite.
5. How `context get` reports missing keys. It should fail clearly and write the value to stdout on success.
6. How `run` loads context values and appends them to the prompt.
7. A deterministic context rendering format. Sort keys.
8. Logging and error-handling expectations.
9. The stage boundary: keep dependencies minimal and preserve existing `run` behavior.
10. The stage 2 bootstrap chain requirement: stage 2 must also update `config/propagate.yaml` to target stage 3 and create `config/prompts/design-stage3.md`, `config/prompts/implement-stage3.md`, and `config/prompts/review-stage3.md`.

## Full Propagate vision

Propagate is a self-hosting CLI that orchestrates agent work across repositories. The full design eventually includes:

- A YAML config with sections such as `version`, `includes`, `defaults`, `repositories`, `context_sources`, `executions`, and `propagation`
- Executions composed of sequential sub-tasks, each driven by a prompt file and later also optional hooks and wait conditions
- A context bag with local, task, and global scopes; stage 2 only introduces the local scope
- Hooks around agent calls for loading context sources, validation, and operational commands
- Git automation after sub-tasks
- Signal-driven triggering from PR events and task completion
- Cross-repo propagation with DAG fan-out and fan-in

The bootstrapping chain matters:

- Stage 1: config-driven execution, no context bag
- Stage 2: local context bag and prompt injection
- Stage 3: hooks and context sources
- Stage 4: git automation
- Stage 5: signals and propagation triggers
- Stage 6: multi-repo DAG orchestration

Each stage must produce the runtime for the next stage plus the config and prompts that allow the next stage to continue the chain.

Future-compatibility note for the design:

- Stage 2 should define a key policy that blocks path traversal and filesystem-unsafe names without painting later stages into a corner.
- In particular, `:`-prefixed keys must remain representable because stage 3 hooks will load context sources via `propagate context set :source-name`.
- If stage 2 reserves `:`-prefixed keys for future use, the design should say so explicitly rather than banning `:` outright.

## Current stage 1 code

The current `propagate.py` is reproduced below and should be treated as the exact starting point for the next sub-task:

```python
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml


LOGGER = logging.getLogger("propagate")


class PropagateError(Exception):
    """Raised when the CLI encounters a user-facing configuration error."""


@dataclass(frozen=True)
class AgentConfig:
    command: str


@dataclass(frozen=True)
class SubTaskConfig:
    task_id: str
    prompt_path: Path


@dataclass(frozen=True)
class ExecutionConfig:
    name: str
    sub_tasks: list[SubTaskConfig]


@dataclass(frozen=True)
class Config:
    version: str
    agent: AgentConfig
    executions: dict[str, ExecutionConfig]
    config_path: Path


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="propagate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run an execution from a config file.")
    run_parser.add_argument("--config", required=True, help="Path to the Propagate YAML config.")
    run_parser.add_argument("--execution", help="Execution name to run.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            return run_command(args.config, args.execution)
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
    run_execution(execution, config.agent.command, Path.cwd())
    LOGGER.info("Execution '%s' completed successfully.", execution.name)
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
    if version != "1":
        raise PropagateError("Config version must be '1' for stage 1.")

    agent = parse_agent(raw_data.get("agent"))
    executions = parse_executions(raw_data.get("executions"), resolved_config_path.parent)

    return Config(version=version, agent=agent, executions=executions, config_path=resolved_config_path)


def parse_agent(agent_data: Any) -> AgentConfig:
    if not isinstance(agent_data, dict):
        raise PropagateError("Config must include an 'agent' mapping.")

    command = agent_data.get("command")
    if not isinstance(command, str) or not command.strip():
        raise PropagateError("Config 'agent.command' must be a non-empty string.")

    if "{prompt_file}" not in command:
        raise PropagateError("Config 'agent.command' must contain the '{prompt_file}' placeholder.")

    return AgentConfig(command=command)


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

        sub_tasks.append(SubTaskConfig(task_id=task_id, prompt_path=prompt_path))

    return ExecutionConfig(name=name, sub_tasks=sub_tasks)


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


def run_execution(execution: ExecutionConfig, agent_command: str, working_dir: Path) -> None:
    for sub_task in execution.sub_tasks:
        run_sub_task(sub_task, agent_command, working_dir)


def run_sub_task(sub_task: SubTaskConfig, agent_command: str, working_dir: Path) -> None:
    LOGGER.info("Starting sub-task '%s' using prompt %s", sub_task.task_id, sub_task.prompt_path)
    prompt_contents = read_prompt_file(sub_task.prompt_path)

    temp_prompt_path: Path | None = None
    try:
        temp_prompt_path = write_temp_prompt_file(sub_task.task_id, prompt_contents)
        command = agent_command.replace("{prompt_file}", str(temp_prompt_path))
        LOGGER.info("Running agent command for sub-task '%s'.", sub_task.task_id)
        subprocess.run(command, shell=True, cwd=working_dir, check=True)
        LOGGER.info("Completed sub-task '%s'.", sub_task.task_id)
    except OSError as error:
        raise PropagateError(f"Failed to execute agent command for sub-task '{sub_task.task_id}': {error}") from error
    except subprocess.CalledProcessError as error:
        raise PropagateError(
            f"Agent command failed for sub-task '{sub_task.task_id}' with exit code {error.returncode}."
        ) from error
    finally:
        if temp_prompt_path is not None:
            remove_temp_prompt_file(temp_prompt_path)


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


if __name__ == "__main__":
    sys.exit(main())
```
