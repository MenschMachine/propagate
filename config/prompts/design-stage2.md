# Stage 2 Design Task

You are designing stage 2 of Propagate. The repository is currently at stage 1. Do not implement the code in this sub-task except for tiny edits that are strictly required to write down the design cleanly.

## What stage 2 must add

- `propagate context set <key> <value>`
- `propagate context get <key>`
- A local file-backed context bag at `.propagate-context/<key>`
- Automatic context injection during `propagate run`: append all local context values to the prompt content before the temporary prompt file is written and passed to the configured agent command

## What stage 2 must not add

- No hooks
- No git automation
- No signals or propagation
- No includes
- No defaults
- No guidelines
- No package restructuring

## Deliverables for this sub-task

1. Write an implementation-ready design doc at `docs/context-bag-stage-2-design.md`.
2. Cover CLI changes, storage format, validation, rendering, logging, error handling, and tests.
3. Define how stage 2 advances the bootstrap chain to stage 3.

## Required design details

The design doc must explicitly define all of the following:

1. CLI shape:
   - `propagate run --config <path> [--execution <name>]`
   - `propagate context set <key> <value>`
   - `propagate context get <key>`
2. Context directory location:
   - Always use `Path.cwd() / ".propagate-context"`.
   - This is based on the invocation working directory, not the config location.
3. Key validation:
   - Reject empty keys.
   - Reject `/`, `\\`, whitespace, `.` and `..`, and traversal-like names.
   - Allow a single leading `:` so future context-source keys like `:openapi-spec` remain valid in stage 3.
   - Keep filenames literal; do not encode keys.
4. `context set` behavior:
   - Create the directory if needed.
   - Overwrite existing values completely.
   - Write UTF-8 text with no automatic newline.
   - Use an atomic replace pattern if practical.
5. `context get` behavior:
   - Read a single file and write its exact contents to stdout.
   - Missing keys must fail clearly.
6. `run` integration:
   - Load local context fresh for every sub-task.
   - Sort keys deterministically.
   - Append a Markdown section labeled exactly `## Context`.
7. Rendering format:

```markdown
## Context

### key-one
value one

### key-two
value two
```

8. Logging and errors:
   - Preserve stage-1 run lifecycle logging.
   - `context set` may log success.
   - `context get` should not log the value.
   - Raise user-facing errors rather than swallowing exceptions.
9. Tests:
   - Cover set/get behavior, missing keys, invalid keys, context injection, and deterministic ordering.
10. Bootstrap output for stage 3:
   - Stage 2 must update `config/propagate.yaml` to version `"2"`.
   - Rename the execution to `build-stage3`.
   - Use the standard six-step chain: design, implement, test, refactor, verify, review.
   - Produce:
     - `config/prompts/design-stage3.md`
     - `config/prompts/implement-stage3.md`
     - `config/prompts/test-stage3.md`
     - `config/prompts/refactor-stage3.md`
     - `config/prompts/verify-stage3.md`
     - `config/prompts/review-stage3.md`
   - Stage 3 adds hooks and named context sources that can load values into the local context bag.

## Full Propagate vision

Propagate is a self-hosting CLI that orchestrates agent work across repositories. The final system is config-driven and LLM-agnostic: the only agent integration is a configured shell command containing `{prompt_file}`. Propagate writes a prompt to a temporary file, substitutes the placeholder, and runs the command in the working directory.

The full design eventually includes these config sections:

- `version`
- `agent`
- `includes`
- `defaults`
- `repositories`
- `context_sources`
- `executions`
- `propagation`

The staged roadmap is:

- Stage 1: config parsing, execution selection, sequential sub-task execution, agent invocation
- Stage 2: local context bag and prompt injection
- Stage 3: hooks and context sources
- Stage 4: git automation
- Stage 5: signal-triggered propagation
- Stage 6: multi-repo and DAG orchestration

Future stages rely on stage 2 making good choices now:

- Hooks in stage 3 will use the context bag to load named context sources via keys like `:source-name`.
- Git automation in stage 4 will use context to build commit metadata.
- Signal handling in stage 5 will inject runtime metadata into the bag.
- Multi-repo orchestration in stage 6 will extend context scope beyond the local store.

## Current stage 1 code

Treat the following as the exact baseline implementation that stage 2 must extend:

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
