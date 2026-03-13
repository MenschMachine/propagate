from pathlib import Path

from .constants import LOGGER
from .context_sources import run_context_source
from .context_store import read_context_value, resolve_execution_context_dir
from .errors import PropagateError
from .models import GitCommitConfig, GitPrConfig, GitPushConfig, RuntimeContext
from .processes import run_git_command, run_process_command
from .temp_files import cleanup_temp_file, write_temp_text


def load_commit_message(commit_config: GitCommitConfig, runtime_context: RuntimeContext, execution_name: str) -> str:
    if commit_config.message_source is not None:
        source_name = commit_config.message_source
        LOGGER.info("Loading commit message from context source '%s'.", source_name)
        message = run_context_source(
            runtime_context.context_sources[source_name],
            runtime_context,
            f"execution '{execution_name}'",
        )
    else:
        message_key = commit_config.message_key
        if message_key is None:
            raise PropagateError("Git commit configuration is missing a message source.")
        LOGGER.info("Loading commit message from context key '%s'.", message_key)
        context_dir = resolve_execution_context_dir(runtime_context)
        message = read_context_value(context_dir, message_key)
    validate_commit_message(message)
    return message


def validate_commit_message(message: str) -> None:
    if not message.strip():
        raise PropagateError("Git commit message must not be empty or whitespace only.")
    if not message.splitlines()[0].strip():
        raise PropagateError("Git commit message must start with a non-empty subject line.")


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
    return lines[0].strip(), "\n".join(lines[1:])
