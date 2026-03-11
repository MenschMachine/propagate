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
from typing import Any, NoReturn, Sequence

import yaml


LOGGER = logging.getLogger("propagate")
CONTEXT_KEY_PATTERN = re.compile(r"^:?[A-Za-z0-9][A-Za-z0-9._-]*$")
CONTEXT_SOURCE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PropagateError(Exception):
    """Raised when the CLI encounters a user-facing error."""


@dataclass(frozen=True)
class AgentConfig:
    command: str


@dataclass(frozen=True)
class ContextSourceConfig:
    name: str
    command: str


@dataclass(frozen=True)
class GitBranchConfig:
    name: str | None
    base: str | None
    reuse: bool


@dataclass(frozen=True)
class GitCommitConfig:
    message_source: str | None
    message_key: str | None


@dataclass(frozen=True)
class GitPushConfig:
    remote: str


@dataclass(frozen=True)
class GitPrConfig:
    base: str | None
    draft: bool


@dataclass(frozen=True)
class GitConfig:
    branch: GitBranchConfig
    commit: GitCommitConfig
    push: GitPushConfig | None
    pr: GitPrConfig | None


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
    git: GitConfig | None


@dataclass(frozen=True)
class Config:
    version: str
    agent: AgentConfig
    context_sources: dict[str, ContextSourceConfig]
    executions: dict[str, ExecutionConfig]
    config_path: Path


@dataclass(frozen=True)
class RuntimeContext:
    agent_command: str
    context_sources: dict[str, ContextSourceConfig]
    working_dir: Path


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

    set_parser = context_subparsers.add_parser("set", help="Store a local context value.")
    set_parser.add_argument("key")
    set_parser.add_argument("value")

    get_parser = context_subparsers.add_parser("get", help="Read a local context value.")
    get_parser.add_argument("key")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    working_dir = Path.cwd()

    try:
        command_result = dispatch_command(args, working_dir)
        if command_result is not None:
            return command_result
    except PropagateError as error:
        LOGGER.error("%s", error)
        return 1
    except KeyboardInterrupt:
        LOGGER.error("Execution interrupted.")
        return 130

    parser.error(f"Unsupported command: {args.command}")
    return 2


def dispatch_command(args: argparse.Namespace, working_dir: Path) -> int | None:
    if args.command == "run":
        return run_command(args.config, args.execution)
    if args.command == "context":
        return dispatch_context_command(args, working_dir)
    return None


def dispatch_context_command(args: argparse.Namespace, working_dir: Path) -> int | None:
    if args.context_command == "set":
        return context_set_command(args.key, args.value, working_dir)
    if args.context_command == "get":
        return context_get_command(args.key, working_dir)
    return None


def run_command(config_value: str, execution_name: str | None) -> int:
    config_path = Path(config_value).expanduser()
    config = load_config(config_path)
    execution = select_execution(config, execution_name)
    runtime_context = RuntimeContext(
        agent_command=config.agent.command,
        context_sources=config.context_sources,
        working_dir=Path.cwd(),
    )

    LOGGER.info("Running execution '%s' with %d sub-task(s).", execution.name, len(execution.sub_tasks))
    if execution.git is None:
        run_execution(execution, runtime_context)
    else:
        run_execution_with_git(execution, runtime_context)
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

    validate_allowed_keys(raw_data, {"version", "agent", "context_sources", "executions"}, "Config")

    version = raw_data.get("version")
    if version != "4":
        raise PropagateError("Config version must be '4' for stage 4.")

    agent = parse_agent(raw_data.get("agent"))
    context_sources = parse_context_sources(raw_data.get("context_sources"))
    executions = parse_executions(
        raw_data.get("executions"),
        resolved_config_path.parent,
        set(context_sources),
    )

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

    validate_allowed_keys(agent_data, {"command"}, "Config 'agent'")

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
        context_sources[source_name] = parse_context_source(source_name, source_data)

    return context_sources


def parse_context_source(source_name: Any, source_data: Any) -> ContextSourceConfig:
    validated_name = validate_context_source_name(source_name)
    if not isinstance(source_data, dict):
        raise PropagateError(f"Context source '{validated_name}' must be a mapping.")

    validate_allowed_keys(source_data, {"command"}, f"Context source '{validated_name}'")
    command = source_data.get("command")
    if not isinstance(command, str) or not command.strip():
        raise PropagateError(f"Context source '{validated_name}' must include a non-empty 'command'.")

    return ContextSourceConfig(name=validated_name, command=command)


def validate_context_source_name(source_name: Any) -> str:
    if not isinstance(source_name, str) or not CONTEXT_SOURCE_NAME_PATTERN.fullmatch(source_name):
        raise PropagateError(f"Invalid context source name '{source_name}'.")
    return source_name


def parse_executions(
    executions_data: Any,
    config_dir: Path,
    context_source_names: set[str],
) -> dict[str, ExecutionConfig]:
    if not isinstance(executions_data, dict) or not executions_data:
        raise PropagateError("Config must include at least one execution in 'executions'.")

    executions: dict[str, ExecutionConfig] = {}
    for execution_name, execution_data in executions_data.items():
        if not isinstance(execution_name, str) or not execution_name.strip():
            raise PropagateError("Execution names must be non-empty strings.")
        executions[execution_name] = parse_execution(
            execution_name,
            execution_data,
            config_dir,
            context_source_names,
        )

    return executions


def parse_execution(
    name: str,
    execution_data: Any,
    config_dir: Path,
    context_source_names: set[str],
) -> ExecutionConfig:
    if not isinstance(execution_data, dict):
        raise PropagateError(f"Execution '{name}' must be a mapping.")

    validate_allowed_keys(execution_data, {"sub_tasks", "git"}, f"Execution '{name}'")

    sub_tasks_data = execution_data.get("sub_tasks")
    if not isinstance(sub_tasks_data, list) or not sub_tasks_data:
        raise PropagateError(f"Execution '{name}' must define a non-empty 'sub_tasks' list.")

    sub_tasks = [
        parse_sub_task(name, index, sub_task_data, config_dir, context_source_names)
        for index, sub_task_data in enumerate(sub_tasks_data, start=1)
    ]

    return ExecutionConfig(
        name=name,
        sub_tasks=sub_tasks,
        git=parse_git_config(name, execution_data.get("git"), context_source_names),
    )


def parse_git_config(
    execution_name: str,
    git_data: Any,
    context_source_names: set[str],
) -> GitConfig | None:
    if git_data is None:
        return None
    if not isinstance(git_data, dict):
        raise PropagateError(f"Execution '{execution_name}' git config must be a mapping.")

    validate_allowed_keys(git_data, {"branch", "commit", "push", "pr"}, f"Execution '{execution_name}' git")

    branch = parse_git_branch_config(execution_name, git_data.get("branch"))
    commit = parse_git_commit_config(execution_name, git_data.get("commit"), context_source_names)
    push = parse_git_push_config(execution_name, git_data.get("push"))
    pr = parse_git_pr_config(execution_name, git_data.get("pr"))

    if pr is not None and push is None:
        raise PropagateError(f"Execution '{execution_name}' git.pr requires git.push to be configured.")

    return GitConfig(branch=branch, commit=commit, push=push, pr=pr)


def parse_git_branch_config(execution_name: str, branch_data: Any) -> GitBranchConfig:
    location = f"Execution '{execution_name}' git.branch"
    if not isinstance(branch_data, dict):
        raise PropagateError(f"{location} must be a mapping.")

    validate_allowed_keys(branch_data, {"name", "base", "reuse"}, location)

    name = optional_non_empty_string(branch_data.get("name"), f"{location}.name")
    base = optional_non_empty_string(branch_data.get("base"), f"{location}.base")
    reuse = branch_data.get("reuse", True)
    if not isinstance(reuse, bool):
        raise PropagateError(f"{location}.reuse must be a boolean when provided.")

    return GitBranchConfig(name=name, base=base, reuse=reuse)


def parse_git_commit_config(
    execution_name: str,
    commit_data: Any,
    context_source_names: set[str],
) -> GitCommitConfig:
    location = f"Execution '{execution_name}' git.commit"
    if not isinstance(commit_data, dict):
        raise PropagateError(f"{location} must be a mapping.")

    validate_allowed_keys(commit_data, {"message_source", "message_key"}, location)

    message_source = commit_data.get("message_source")
    message_key = commit_data.get("message_key")
    if (message_source is None) == (message_key is None):
        raise PropagateError(f"{location} must define exactly one of 'message_source' or 'message_key'.")

    if message_source is not None:
        source_name = validate_context_source_name(message_source)
        if source_name not in context_source_names:
            raise PropagateError(
                f"{location}.message_source references unknown context source '{source_name}'."
            )
        return GitCommitConfig(message_source=source_name, message_key=None)

    validated_key = validate_context_key(message_key)
    if not validated_key.startswith(":"):
        raise PropagateError(f"{location}.message_key must use a reserved ':'-prefixed context key.")
    return GitCommitConfig(message_source=None, message_key=validated_key)


def parse_git_push_config(execution_name: str, push_data: Any) -> GitPushConfig | None:
    if push_data is None:
        return None
    location = f"Execution '{execution_name}' git.push"
    if not isinstance(push_data, dict):
        raise PropagateError(f"{location} must be a mapping.")

    validate_allowed_keys(push_data, {"remote"}, location)

    remote = push_data.get("remote")
    if not isinstance(remote, str) or not remote.strip():
        raise PropagateError(f"{location}.remote must be a non-empty string.")

    return GitPushConfig(remote=remote)


def parse_git_pr_config(execution_name: str, pr_data: Any) -> GitPrConfig | None:
    if pr_data is None:
        return None
    location = f"Execution '{execution_name}' git.pr"
    if not isinstance(pr_data, dict):
        raise PropagateError(f"{location} must be a mapping.")

    validate_allowed_keys(pr_data, {"base", "draft"}, location)

    base = optional_non_empty_string(pr_data.get("base"), f"{location}.base")
    draft = pr_data.get("draft", False)
    if not isinstance(draft, bool):
        raise PropagateError(f"{location}.draft must be a boolean when provided.")

    return GitPrConfig(base=base, draft=draft)


def optional_non_empty_string(value: Any, location: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PropagateError(f"{location} must be a non-empty string when provided.")
    return value


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
        on_failure=parse_hook_actions(
            sub_task_data.get("on_failure"),
            location,
            "on_failure",
            context_source_names,
        ),
    )


def parse_hook_actions(
    hook_data: Any,
    location: str,
    phase: str,
    context_source_names: set[str],
) -> list[str]:
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
                raise PropagateError(
                    f"{location} '{phase}' hook #{hook_index} references unknown context source '{source_name}'."
                )
        actions.append(action)

    return actions


def resolve_prompt_path(prompt_value: str, config_dir: Path) -> Path:
    prompt_path = Path(prompt_value).expanduser()
    if prompt_path.is_absolute():
        return prompt_path
    return (config_dir / prompt_path).resolve()


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


def run_execution_with_git(execution: ExecutionConfig, runtime_context: RuntimeContext) -> None:
    git_config = execution.git
    if git_config is None:
        run_execution(execution, runtime_context)
        return

    LOGGER.info("Git automation enabled for execution '%s'.", execution.name)
    try:
        ensure_git_repository(runtime_context.working_dir)
        starting_branch = get_current_branch(runtime_context.working_dir)
        LOGGER.info("Detected starting branch '%s'.", starting_branch)
        ensure_clean_working_tree(runtime_context.working_dir)
    except PropagateError as error:
        raise cannot_start_execution_git_automation(execution.name, error) from error

    try:
        target_branch = resolve_execution_branch_name(
            git_config.branch,
            execution.name,
            runtime_context.working_dir,
        )
        base_ref = git_config.branch.base or starting_branch
        selected_branch = prepare_execution_branch(
            target_branch,
            base_ref,
            git_config.branch.reuse,
            starting_branch,
            runtime_context.working_dir,
        )
    except PropagateError as error:
        raise wrap_execution_git_phase_error(execution.name, "branch setup", error) from error

    run_execution(execution, runtime_context)

    if not working_tree_has_changes(runtime_context.working_dir):
        LOGGER.info(
            "No repository changes detected after execution '%s'; skipping commit, push, and PR steps.",
            execution.name,
        )
        return

    try:
        commit_message = load_commit_message(git_config.commit, runtime_context, execution.name)
    except PropagateError as error:
        raise wrap_execution_git_phase_error(execution.name, "commit-message generation", error) from error

    try:
        create_execution_commit(commit_message, runtime_context.working_dir)
    except PropagateError as error:
        raise wrap_execution_git_phase_error(execution.name, "commit creation", error) from error

    if git_config.push is not None:
        try:
            push_branch(git_config.push, selected_branch, runtime_context.working_dir)
        except PropagateError as error:
            raise wrap_execution_git_phase_error(execution.name, "push", error) from error

    if git_config.pr is not None:
        pr_base = git_config.pr.base or git_config.branch.base or starting_branch
        try:
            create_pull_request(
                git_config.pr,
                pr_base,
                selected_branch,
                commit_message,
                runtime_context.working_dir,
            )
        except PropagateError as error:
            raise wrap_execution_git_phase_error(execution.name, "PR creation", error) from error


def cannot_start_execution_git_automation(execution_name: str, error: PropagateError) -> PropagateError:
    return PropagateError(
        f"Execution '{execution_name}' cannot start git automation: {normalize_error_message(str(error))}."
    )


def wrap_execution_git_phase_error(
    execution_name: str,
    phase: str,
    error: PropagateError,
) -> PropagateError:
    return PropagateError(
        f"Execution '{execution_name}' failed during {phase}: {normalize_error_message(str(error))}."
    )


def normalize_error_message(message: str) -> str:
    return message.rstrip().rstrip(".")


def ensure_git_repository(working_dir: Path) -> None:
    result = run_git_command(
        ["rev-parse", "--is-inside-work-tree"],
        working_dir,
        failure_message="Git automation requires the working directory to be inside a git work tree.",
        start_failure_message="Failed to start git repository check: {error}",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise PropagateError("Git automation requires the working directory to be inside a git work tree.")


def get_current_branch(working_dir: Path) -> str:
    result = run_git_command(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        working_dir,
        failure_message="Failed to detect the current git branch.",
        start_failure_message="Failed to start current branch detection: {error}",
        capture_output=True,
    )
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        raise PropagateError("Git automation requires a checked-out branch at run start.")
    return branch


def ensure_clean_working_tree(working_dir: Path) -> None:
    LOGGER.info("Checking git working tree for pre-existing changes.")
    if working_tree_has_changes(working_dir):
        raise PropagateError("Git automation requires a clean working tree before execution.")


def working_tree_has_changes(working_dir: Path) -> bool:
    result = run_git_command(
        ["status", "--porcelain", "--untracked-files=all"],
        working_dir,
        failure_message="Failed to inspect git working tree status.",
        start_failure_message="Failed to start git status inspection: {error}",
        capture_output=True,
    )
    return bool(result.stdout.strip())


def resolve_execution_branch_name(
    branch_config: GitBranchConfig,
    execution_name: str,
    working_dir: Path,
) -> str:
    branch_name = branch_config.name or f"propagate/{execution_name}"
    result = run_git_command(
        ["check-ref-format", "--branch", branch_name],
        working_dir,
        failure_message=f"Git branch name '{branch_name}' is invalid.",
        start_failure_message="Failed to validate git branch name: {error}",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise PropagateError(f"Git branch name '{branch_name}' is invalid.")
    return branch_name


def prepare_execution_branch(
    target_branch: str,
    base_ref: str,
    reuse_branch: bool,
    starting_branch: str,
    working_dir: Path,
) -> str:
    if target_branch == starting_branch:
        LOGGER.info("Using already checked out branch '%s'.", target_branch)
        return target_branch

    if local_branch_exists(target_branch, working_dir):
        if not reuse_branch:
            raise PropagateError(f"Git branch '{target_branch}' already exists and reuse is disabled.")
        LOGGER.info("Checking out existing branch '%s'.", target_branch)
        checkout_branch(target_branch, working_dir)
        return target_branch

    ensure_git_ref_exists(base_ref, working_dir)
    LOGGER.info("Creating and checking out branch '%s' from '%s'.", target_branch, base_ref)
    run_git_command(
        ["checkout", "-b", target_branch, base_ref],
        working_dir,
        failure_message=f"Failed to create branch '{target_branch}' from '{base_ref}'.",
        start_failure_message=f"Failed to start branch creation for '{target_branch}': {{error}}",
    )
    return target_branch


def local_branch_exists(branch_name: str, working_dir: Path) -> bool:
    result = run_git_command(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        working_dir,
        failure_message=f"Failed to inspect whether branch '{branch_name}' exists.",
        start_failure_message=f"Failed to start branch inspection for '{branch_name}': {{error}}",
        check=False,
    )
    return result.returncode == 0


def ensure_git_ref_exists(ref_name: str, working_dir: Path) -> None:
    result = run_git_command(
        ["rev-parse", "--verify", "--quiet", f"{ref_name}^{{commit}}"],
        working_dir,
        failure_message=f"Git base ref '{ref_name}' was not found.",
        start_failure_message=f"Failed to start git base ref lookup for '{ref_name}': {{error}}",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise PropagateError(f"Git base ref '{ref_name}' was not found.")


def checkout_branch(branch_name: str, working_dir: Path) -> None:
    run_git_command(
        ["checkout", branch_name],
        working_dir,
        failure_message=f"Failed to checkout branch '{branch_name}'.",
        start_failure_message=f"Failed to start branch checkout for '{branch_name}': {{error}}",
    )


def load_commit_message(
    commit_config: GitCommitConfig,
    runtime_context: RuntimeContext,
    execution_name: str,
) -> str:
    if commit_config.message_source is not None:
        source_name = commit_config.message_source
        LOGGER.info("Loading commit message from context source '%s'.", source_name)
        message = run_execution_context_source(
            runtime_context.context_sources[source_name],
            runtime_context.working_dir,
            execution_name,
        )
    else:
        message_key = commit_config.message_key
        if message_key is None:
            raise PropagateError("Git commit configuration is missing a message source.")
        LOGGER.info("Loading commit message from context key '%s'.", message_key)
        message = read_context_value(get_context_dir(runtime_context.working_dir), message_key)

    validate_commit_message(message)
    return message


def validate_commit_message(message: str) -> None:
    if not message.strip():
        raise PropagateError("Git commit message must not be empty or whitespace only.")
    if not message.splitlines()[0].strip():
        raise PropagateError("Git commit message must start with a non-empty subject line.")


def run_execution_context_source(
    context_source: ContextSourceConfig,
    working_dir: Path,
    execution_name: str,
) -> str:
    output = capture_context_source_output(
        context_source.command,
        working_dir,
        failure_message=(
            f"Context source '{context_source.name}' failed for execution '{execution_name}' with exit code "
            "{{exit_code}}."
        ),
        start_failure_message=(
            f"Failed to start context source '{context_source.name}' for execution '{execution_name}': {{error}}"
        ),
    )
    store_context_source_output(context_source.name, output, working_dir)
    return output


def create_execution_commit(commit_message: str, working_dir: Path) -> None:
    LOGGER.info("Creating git commit for execution changes.")
    run_git_command(
        ["add", "-A"],
        working_dir,
        failure_message="Failed to stage execution changes for commit.",
        start_failure_message="Failed to start git add for execution changes: {error}",
    )

    message_path = write_temp_text(commit_message, prefix="propagate-commit-", suffix=".txt")
    try:
        run_git_command(
            ["commit", "-F", str(message_path)],
            working_dir,
            failure_message="Failed to create git commit for execution changes.",
            start_failure_message="Failed to start git commit for execution changes: {error}",
        )
    finally:
        cleanup_temp_file(message_path, "commit message file")


def push_branch(push_config: GitPushConfig, branch_name: str, working_dir: Path) -> None:
    LOGGER.info("Pushing branch '%s' to remote '%s'.", branch_name, push_config.remote)
    run_git_command(
        ["push", "--set-upstream", push_config.remote, branch_name],
        working_dir,
        failure_message=f"Failed to push branch '{branch_name}' to remote '{push_config.remote}'.",
        start_failure_message=f"Failed to start push to remote '{push_config.remote}': {{error}}",
    )


def create_pull_request(
    pr_config: GitPrConfig,
    base_branch: str,
    head_branch: str,
    commit_message: str,
    working_dir: Path,
) -> None:
    title, body = split_commit_message(commit_message)
    LOGGER.info("Creating pull request from '%s' into '%s'.", head_branch, base_branch)

    body_path = write_temp_text(body, prefix="propagate-pr-", suffix=".md")
    try:
        command = [
            "gh",
            "pr",
            "create",
            "--base",
            base_branch,
            "--head",
            head_branch,
            "--title",
            title,
            "--body-file",
            str(body_path),
        ]
        if pr_config.draft:
            command.append("--draft")
        run_process_command(
            command,
            working_dir,
            failure_message=f"Failed to create pull request for branch '{head_branch}'.",
            start_failure_message="Failed to start pull request creation: {error}",
            capture_output=True,
        )
    finally:
        cleanup_temp_file(body_path, "pull request body file")


def split_commit_message(commit_message: str) -> tuple[str, str]:
    lines = commit_message.splitlines()
    title = lines[0].strip()
    body = "\n".join(lines[1:])
    return title, body


def run_execution(execution: ExecutionConfig, runtime_context: RuntimeContext) -> None:
    for sub_task in execution.sub_tasks:
        run_sub_task(execution.name, sub_task, runtime_context)


def run_sub_task(
    execution_name: str,
    sub_task: SubTaskConfig,
    runtime_context: RuntimeContext,
) -> None:
    LOGGER.info(
        "Running sub-task '%s' for execution '%s' using prompt '%s'.",
        sub_task.task_id,
        execution_name,
        sub_task.prompt_path,
    )

    run_before_hooks(sub_task, runtime_context)

    temp_prompt_path = prepare_sub_task_prompt(sub_task, runtime_context.working_dir)
    try:
        run_sub_task_agent(sub_task, temp_prompt_path, runtime_context)
    finally:
        cleanup_temp_file(temp_prompt_path, "temporary prompt file")

    run_after_hooks(sub_task, runtime_context)

    LOGGER.info("Completed sub-task '%s' for execution '%s'.", sub_task.task_id, execution_name)


def run_before_hooks(sub_task: SubTaskConfig, runtime_context: RuntimeContext) -> None:
    try:
        run_hook_phase(
            sub_task.task_id,
            "before",
            sub_task.before,
            runtime_context.context_sources,
            runtime_context.working_dir,
        )
    except PropagateError as error:
        handle_sub_task_failure(sub_task, runtime_context.context_sources, runtime_context.working_dir, error)


def prepare_sub_task_prompt(sub_task: SubTaskConfig, working_dir: Path) -> Path:
    prompt_text = build_sub_task_prompt(sub_task.prompt_path, sub_task.task_id, working_dir)
    return write_temp_text(prompt_text, prefix="propagate-", suffix=".md")


def run_sub_task_agent(sub_task: SubTaskConfig, temp_prompt_path: Path, runtime_context: RuntimeContext) -> None:
    command = build_agent_command(runtime_context.agent_command, temp_prompt_path)
    try:
        run_agent_command(command, runtime_context.working_dir, sub_task.task_id)
    except PropagateError as error:
        handle_sub_task_failure(sub_task, runtime_context.context_sources, runtime_context.working_dir, error)


def run_after_hooks(sub_task: SubTaskConfig, runtime_context: RuntimeContext) -> None:
    try:
        run_hook_phase(
            sub_task.task_id,
            "after",
            sub_task.after,
            runtime_context.context_sources,
            runtime_context.working_dir,
        )
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

        LOGGER.info(
            "Running %s hook %d/%d for sub-task '%s'.",
            phase,
            hook_index,
            total_actions,
            task_id,
        )
        run_hook_command(action, phase, hook_index, task_id, working_dir)


def run_context_source(context_source: ContextSourceConfig, working_dir: Path, task_id: str) -> None:
    output = capture_context_source_output(
        context_source.command,
        working_dir,
        failure_message=(
            f"Context source '{context_source.name}' failed for sub-task '{task_id}' with exit code {{exit_code}}."
        ),
        start_failure_message=(
            f"Failed to start context source '{context_source.name}' for sub-task '{task_id}': {{error}}"
        ),
    )
    store_context_source_output(context_source.name, output, working_dir)


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
    return result.stdout


def store_context_source_output(source_name: str, value: str, working_dir: Path) -> None:
    context_set_command(f":{source_name}", value, working_dir)


def run_hook_command(command: str, phase: str, hook_index: int, task_id: str, working_dir: Path) -> None:
    run_shell_command(
        command,
        working_dir,
        failure_message=build_hook_failure_message(phase, hook_index, task_id, "{exit_code}"),
        start_failure_message=f"Failed to start {phase} hook #{hook_index} for sub-task '{task_id}': {{error}}",
    )


def build_hook_failure_message(phase: str, hook_index: int, task_id: str, exit_code: int | str) -> str:
    return f"{get_hook_phase_display_name(phase)} hook #{hook_index} failed for sub-task '{task_id}' with exit code {exit_code}."


def get_hook_phase_display_name(phase: str) -> str:
    if phase == "before":
        return "Before"
    if phase == "after":
        return "After"
    if phase == "on_failure":
        return "on_failure"
    return phase


def build_sub_task_prompt(prompt_path: Path, task_id: str, working_dir: Path) -> str:
    prompt_text = read_prompt(prompt_path)
    context_dir = get_context_dir(working_dir)
    LOGGER.info("Loading local context for sub-task '%s' from '%s'.", task_id, context_dir)
    context_items = load_local_context(context_dir)
    return append_context_to_prompt(prompt_text, context_items)


def read_prompt(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise PropagateError(f"Prompt file does not exist: {prompt_path}")
    if not prompt_path.is_file():
        raise PropagateError(f"Prompt path is not a file: {prompt_path}")

    try:
        return prompt_path.read_text(encoding="utf-8")
    except OSError as error:
        raise PropagateError(f"Failed to read prompt file {prompt_path}: {error}") from error


def write_temp_text(content: str, prefix: str, suffix: str) -> Path:
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=prefix,
            suffix=suffix,
            delete=False,
        ) as handle:
            handle.write(content)
    except OSError as error:
        raise PropagateError(f"Failed to write temporary file: {error}") from error

    return Path(handle.name)


def get_context_dir(working_dir: Path) -> Path:
    return working_dir / ".propagate-context"


def validate_context_key(key: Any) -> str:
    if not isinstance(key, str) or not CONTEXT_KEY_PATTERN.fullmatch(key):
        raise PropagateError(f"Invalid context key '{key}'.")

    return key


def context_set_command(key: str, value: str, working_dir: Path) -> int:
    validated_key = validate_context_key(key)
    context_dir = get_context_dir(working_dir)

    ensure_context_dir(context_dir)

    write_context_value(context_dir, validated_key, value)
    LOGGER.info("Stored context key '%s'.", validated_key)
    return 0


def context_get_command(key: str, working_dir: Path) -> int:
    value = read_context_value(get_context_dir(working_dir), validate_context_key(key))
    sys.stdout.write(value)
    return 0


def ensure_context_dir(context_dir: Path) -> None:
    try:
        context_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PropagateError(f"Failed to create context directory {context_dir}: {error}") from error

    if not context_dir.is_dir():
        raise PropagateError(f"Context path is not a directory: {context_dir}")


def write_context_value(context_dir: Path, key: str, value: str) -> None:
    temp_path: Path | None = None
    target_path = context_dir / key

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{key}.",
            suffix=".tmp",
            dir=context_dir,
            delete=False,
        ) as handle:
            handle.write(value)
            temp_path = Path(handle.name)

        temp_path.replace(target_path)
    except OSError as error:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise PropagateError(f"Failed to write context key '{key}' in {context_dir}: {error}") from error


def read_context_value(context_dir: Path, key: str) -> str:
    require_context_dir(context_dir)
    context_path = context_dir / key
    if not context_path.exists():
        raise PropagateError(f"Context key '{key}' was not found in {context_dir}.")
    return read_context_entry(context_dir, key, context_path)


def load_local_context(context_dir: Path) -> list[tuple[str, str]]:
    if not context_dir.exists():
        return []
    require_context_dir(context_dir)

    items: list[tuple[str, str]] = []
    try:
        entries = sorted(context_dir.iterdir(), key=lambda entry: entry.name)
    except OSError as error:
        raise PropagateError(f"Failed to read context directory {context_dir}: {error}") from error

    for entry in entries:
        key = validate_context_key(entry.name)
        items.append((key, read_context_entry(context_dir, key, entry)))

    return items


def require_context_dir(context_dir: Path) -> None:
    if not context_dir.exists():
        raise PropagateError(f"Context directory does not exist: {context_dir}")
    if not context_dir.is_dir():
        raise PropagateError(f"Context path is not a directory: {context_dir}")


def read_context_entry(context_dir: Path, key: str, entry_path: Path) -> str:
    if not entry_path.is_file():
        raise PropagateError(f"Context entry '{key}' is not a file in {context_dir}.")

    try:
        return entry_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise PropagateError(f"Failed to decode context key '{key}' in {context_dir} as UTF-8: {error}") from error
    except OSError as error:
        raise PropagateError(f"Failed to read context key '{key}' in {context_dir}: {error}") from error


def render_context_section(items: list[tuple[str, str]]) -> str:
    blocks: list[str] = []
    for key, value in items:
        rendered_value = value if value.endswith("\n") else f"{value}\n"
        blocks.append(f"### {key}\n{rendered_value}")

    return "## Context\n\n" + "\n".join(blocks).rstrip("\n") + "\n"


def append_context_to_prompt(prompt_text: str, items: list[tuple[str, str]]) -> str:
    if not items:
        return prompt_text

    context_section = render_context_section(items)
    if not prompt_text:
        return context_section
    if prompt_text.endswith("\n\n"):
        return f"{prompt_text}{context_section}"
    if prompt_text.endswith("\n"):
        return f"{prompt_text}\n{context_section}"
    return f"{prompt_text}\n\n{context_section}"


def build_agent_command(agent_command: str, prompt_file: Path) -> str:
    return agent_command.replace("{prompt_file}", shlex.quote(str(prompt_file)))


def run_agent_command(command: str, working_dir: Path, task_id: str) -> None:
    run_shell_command(
        command,
        working_dir,
        failure_message=f"Agent command failed for sub-task '{task_id}' with exit code {{exit_code}}.",
        start_failure_message=f"Failed to start agent command for sub-task '{task_id}': {{error}}",
    )


def run_shell_command(
    command: str,
    working_dir: Path,
    failure_message: str,
    start_failure_message: str,
    *,
    capture_output: bool = False,
    text: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            shell=True,
            cwd=working_dir,
            check=True,
            capture_output=capture_output,
            text=text,
        )
    except subprocess.CalledProcessError as error:
        raise PropagateError(failure_message.format(exit_code=error.returncode)) from error
    except OSError as error:
        raise PropagateError(start_failure_message.format(error=error)) from error


def run_process_command(
    command: Sequence[str],
    working_dir: Path,
    failure_message: str,
    start_failure_message: str,
    *,
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=working_dir,
            check=check,
            capture_output=capture_output,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise PropagateError(build_process_failure_message(failure_message, error)) from error
    except OSError as error:
        raise PropagateError(start_failure_message.format(error=error)) from error


def build_process_failure_message(
    failure_message: str,
    error: subprocess.CalledProcessError,
) -> str:
    message = failure_message.format(exit_code=error.returncode)
    stderr_excerpt = format_stderr_excerpt(error.stderr)
    if stderr_excerpt is None:
        return message
    return f"{message} stderr: {stderr_excerpt}"


def format_stderr_excerpt(stderr: str | None) -> str | None:
    if stderr is None:
        return None

    excerpt = " ".join(stderr.strip().split())
    if not excerpt:
        return None
    if len(excerpt) <= 240:
        return excerpt
    return f"{excerpt[:237].rstrip()}..."


def run_git_command(
    git_args: Sequence[str],
    working_dir: Path,
    failure_message: str,
    start_failure_message: str,
    *,
    capture_output: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run_process_command(
        ["git", *git_args],
        working_dir,
        failure_message=failure_message,
        start_failure_message=start_failure_message,
        capture_output=capture_output,
        check=check,
    )


def cleanup_temp_file(temp_path: Path, label: str) -> None:
    try:
        temp_path.unlink(missing_ok=True)
    except OSError as error:
        LOGGER.warning("Failed to remove %s '%s': %s", label, temp_path, error)


if __name__ == "__main__":
    raise SystemExit(main())
