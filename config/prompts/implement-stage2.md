# Stage 2 Implementation Task

You are implementing stage 2 of Propagate in place. The repository currently contains a working stage 1 runtime. Extend it to add the local context bag while preserving existing stage 1 behavior.

## Required outputs

You must leave the repository in a stage 2 state. That includes:

1. Update `propagate.py` to add:
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
   - local file-backed context storage in `.propagate-context`
   - prompt augmentation during `propagate run`, appending all context values in a clear `Context` section before the temporary prompt file is written
2. Preserve the stage 1 `run` command semantics.
3. Keep the implementation in a single file and keep dependencies minimal.
4. Update `config/propagate.yaml` so stage 2 targets building stage 3.
5. Create `config/prompts/design-stage3.md`, `config/prompts/implement-stage3.md`, and `config/prompts/review-stage3.md`.
   - These stage 3 prompts should instruct the next run to add hooks and context sources.
   - Because stage 2 has a context bag, those prompts can be leaner than stage 2's prompts, but they still need enough inline context to continue the bootstrapping chain.

## Implementation constraints

- Python 3.10+
- Use logging, not `print()`
- Use type hints
- Use f-strings
- Do not swallow exceptions
- Keep `PyYAML` as the only external dependency
- Continue to resolve prompt paths relative to the config file
- The agent command still receives a temporary prompt file via `{prompt_file}`

## Context bag requirements

Implement stage 2 with these exact semantics:

1. The context directory is `.propagate-context` in the invocation working directory.
2. `propagate context set <key> <value>` writes the value to `.propagate-context/<key>`.
3. `propagate context get <key>` reads the file and writes its contents to stdout exactly.
4. Missing keys must produce a clear non-zero failure.
5. Reject unsafe keys such as empty strings, path separators, or traversal segments.
6. When `propagate run` executes a sub-task, load all context files from `.propagate-context`, sort by key, and append them to the prompt in a deterministic section.
7. Use a readable format, for example:

```markdown
## Context

### release_version
1.2.3

### pr_title
Add hooks support
```

8. If there is no context directory or it is empty, `run` should still work normally.
9. `context set` should create the directory if needed.

## Full Propagate vision

The final system is a config-driven orchestrator for AI agent work across repositories. It evolves across these stages:

- Stage 1: config parsing, sub-task sequencing, agent execution
- Stage 2: local context bag and prompt injection
- Stage 3: hooks and context sources
- Stage 4: git automation
- Stage 5: signals and propagation triggers
- Stage 6: multi-repo and DAG orchestration

The eventual config includes sections such as `version`, `includes`, `defaults`, `repositories`, `context_sources`, `executions`, and `propagation`. Context later grows local, task, and global scopes. Hooks later load context sources and run validations. Git and signals arrive in later stages.

## Current stage 1 code

Start from this exact `propagate.py` state:

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

## Implementation notes

- If the design sub-task created `docs/context-bag-stage-2-design.md`, use it.
- Verify the updated CLI manually after editing.
- Keep the code straightforward. Stage 2 is still a small bootstrap runtime.
