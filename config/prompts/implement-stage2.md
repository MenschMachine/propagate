# Stage 2 Implementation Task

You are implementing stage 2 of Propagate in place. The repository currently contains the stage-1 runtime shown below. Extend it to add the local context bag while preserving existing stage-1 run behavior.

## Required repository end state

1. `propagate.py` is stage 2:
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - `.propagate-context/<key>` local storage
   - prompt augmentation during `propagate run`
2. `config/propagate.yaml` is advanced to stage 2 output for building stage 3:
   - `version: "2"`
   - execution name `build-stage3`
   - six sub-tasks: design, implement, test, refactor, verify, review
3. Stage-3 prompts exist:
   - `config/prompts/design-stage3.md`
   - `config/prompts/implement-stage3.md`
   - `config/prompts/test-stage3.md`
   - `config/prompts/refactor-stage3.md`
   - `config/prompts/verify-stage3.md`
   - `config/prompts/review-stage3.md`

## Stage 2 implementation requirements

- Keep the implementation in `propagate.py`.
- Keep `PyYAML` as the only external dependency.
- Continue resolving prompt paths relative to the config file.
- Keep the working directory for agent execution as the invocation directory.
- Read local context for each sub-task, not just once per execution.
- Render context deterministically in sorted key order.
- Use proper logging and clear user-facing exceptions.

## Context behavior to implement

1. Store local context under `Path.cwd() / ".propagate-context"`.
2. `context set` validates the key, creates the directory if needed, and overwrites the stored value.
3. `context get` validates the key, reads the exact value, and writes it to stdout exactly.
4. During `run`, append this exact Markdown section shape when context exists:

```markdown
## Context

### key-one
value one

### key-two
value two
```

5. Reject unsafe keys and filesystem corruption clearly.
6. If there is no context directory, `run` should behave exactly like stage 1.

## Stage 3 bootstrap target

The next stage adds hooks and named context sources.

The stage-3 prompts you create should instruct the next run to add:

- `before`, `after`, and `on_failure` hooks on sub-tasks
- named context sources in config
- hook-driven loading via keys like `:source-name`
- validation hooks around agent calls

## Full Propagate vision

Propagate is a self-hosting, LLM-agnostic orchestration CLI. The long-term runtime will support:

- config sections `version`, `agent`, `includes`, `defaults`, `repositories`, `context_sources`, `executions`, and `propagation`
- sequential sub-tasks driven by prompt files
- local, task, and global context scopes
- hooks and context-source loading
- git automation after sub-tasks
- signal-driven triggering and cross-repo propagation
- multi-repo DAG orchestration

The staged chain is:

- Stage 1: config parsing and sub-task execution
- Stage 2: local context bag
- Stage 3: hooks and context sources
- Stage 4: git automation
- Stage 5: signals and propagation triggers
- Stage 6: multi-repo DAG orchestration

## Current stage 1 code

Start from this exact `propagate.py` baseline:

```python
from __future__ import annotations

import argparse
import logging
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml


LOGGER = logging.getLogger("propagate")


class PropagateError(Exception):
    """Raised when the CLI encounters a user-facing error."""


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

    validate_allowed_keys(raw_data, {"version", "agent", "executions"}, "Config")

    version = raw_data.get("version")
    if version != "1":
        raise PropagateError("Config version must be '1' for stage 1.")

    agent = parse_agent(raw_data.get("agent"))
    executions = parse_executions(raw_data.get("executions"), resolved_config_path.parent)

    return Config(
        version=version,
        agent=agent,
        executions=executions,
        config_path=resolved_config_path,
    )


def parse_agent(agent_data: Any) -> AgentConfig:
    if not isinstance(agent_data, dict):
        raise PropagateError("Config must include an 'agent' mapping.")

    validate_allowed_keys(agent_data, {"command"}, "Config 'agent'")

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

    validate_allowed_keys(execution_data, {"sub_tasks"}, f"Execution '{name}'")

    sub_tasks_data = execution_data.get("sub_tasks")
    if not isinstance(sub_tasks_data, list) or not sub_tasks_data:
        raise PropagateError(f"Execution '{name}' must define a non-empty 'sub_tasks' list.")

    sub_tasks: list[SubTaskConfig] = []
    for index, sub_task_data in enumerate(sub_tasks_data, start=1):
        if not isinstance(sub_task_data, dict):
            raise PropagateError(f"Execution '{name}' sub-task #{index} must be a mapping.")

        validate_allowed_keys(sub_task_data, {"id", "prompt"}, f"Execution '{name}' sub-task #{index}")

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


def validate_allowed_keys(data: dict[str, Any], allowed_keys: set[str], location: str) -> None:
    unknown_keys = sorted(set(data) - allowed_keys)
    if unknown_keys:
        joined_keys = ", ".join(unknown_keys)
        raise PropagateError(f"{location} has unsupported keys: {joined_keys}")


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
        run_sub_task(execution.name, sub_task, agent_command, working_dir)


def run_sub_task(execution_name: str, sub_task: SubTaskConfig, agent_command: str, working_dir: Path) -> None:
    prompt_text = read_prompt(sub_task.prompt_path)
    temp_prompt_path = write_temp_prompt(prompt_text)

    try:
        command = build_agent_command(agent_command, temp_prompt_path)
        LOGGER.info(
            "Running sub-task '%s' for execution '%s' using prompt '%s'.",
            sub_task.task_id,
            execution_name,
            sub_task.prompt_path,
        )
        run_agent_command(command, working_dir, sub_task.task_id)
    finally:
        cleanup_temp_prompt(temp_prompt_path)


def read_prompt(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise PropagateError(f"Prompt file does not exist: {prompt_path}")
    if not prompt_path.is_file():
        raise PropagateError(f"Prompt path is not a file: {prompt_path}")

    try:
        return prompt_path.read_text(encoding="utf-8")
    except OSError as error:
        raise PropagateError(f"Failed to read prompt file {prompt_path}: {error}") from error


def write_temp_prompt(prompt_text: str) -> Path:
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".md",
            prefix="propagate-",
            delete=False,
        ) as handle:
            handle.write(prompt_text)
    except OSError as error:
        raise PropagateError(f"Failed to write temporary prompt file: {error}") from error

    return Path(handle.name)


def build_agent_command(agent_command: str, prompt_file: Path) -> str:
    return agent_command.replace("{prompt_file}", shlex.quote(str(prompt_file)))


def run_agent_command(command: str, working_dir: Path, task_id: str) -> None:
    try:
        subprocess.run(command, shell=True, cwd=working_dir, check=True)
    except subprocess.CalledProcessError as error:
        raise PropagateError(f"Agent command failed for sub-task '{task_id}' with exit code {error.returncode}.") from error
    except OSError as error:
        raise PropagateError(f"Failed to start agent command for sub-task '{task_id}': {error}") from error


def cleanup_temp_prompt(temp_prompt_path: Path) -> None:
    try:
        temp_prompt_path.unlink(missing_ok=True)
    except OSError as error:
        LOGGER.warning("Failed to remove temporary prompt file '%s': %s", temp_prompt_path, error)


if __name__ == "__main__":
    raise SystemExit(main())
```
