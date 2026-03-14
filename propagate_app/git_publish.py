import json
import time
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
    result = run_git_command(
        ["push", "--set-upstream", push_config.remote, branch_name],
        working_dir,
        failure_message=f"Failed to push branch '{branch_name}' to remote '{push_config.remote}'.",
        start_failure_message=f"Failed to start push to remote '{push_config.remote}': {{error}}",
        check=False,
    )
    if result.returncode == 0:
        return
    LOGGER.debug("Push rejected; attempting fetch and rebase from '%s/%s'.", push_config.remote, branch_name)
    _rebase_and_retry_push(push_config, branch_name, working_dir)


def _rebase_and_retry_push(push_config: GitPushConfig, branch_name: str, working_dir: Path) -> None:
    remote = push_config.remote
    fetch = run_git_command(
        ["fetch", remote, branch_name],
        working_dir,
        failure_message=f"Failed to fetch '{branch_name}' from remote '{remote}'.",
        start_failure_message=f"Failed to start fetch from remote '{remote}': {{error}}",
        check=False,
    )
    if fetch.returncode != 0:
        raise PropagateError(f"Failed to fetch '{branch_name}' from '{remote}' before retrying push.")
    rebase = run_git_command(
        ["rebase", f"{remote}/{branch_name}"],
        working_dir,
        failure_message=f"Rebase onto '{remote}/{branch_name}' failed.",
        start_failure_message="Failed to start rebase: {error}",
        check=False,
    )
    if rebase.returncode != 0:
        LOGGER.debug("Rebase stderr: %s", rebase.stderr)
        abort = run_git_command(
            ["rebase", "--abort"],
            working_dir,
            failure_message="Failed to abort rebase.",
            start_failure_message="Failed to start rebase abort: {error}",
            check=False,
        )
        if abort.returncode != 0:
            LOGGER.warning("Rebase abort failed (returncode %d); repository may be mid-rebase.", abort.returncode)
        raise PropagateError(
            f"Failed to push branch '{branch_name}' to remote '{remote}': "
            f"push was rejected and rebase onto '{remote}/{branch_name}' failed due to conflicts."
        )
    run_git_command(
        ["push", "--set-upstream", remote, branch_name],
        working_dir,
        failure_message=f"Failed to push branch '{branch_name}' to remote '{remote}' after rebase.",
        start_failure_message=f"Failed to start push to remote '{remote}': {{error}}",
    )


def create_pull_request(
    pr_config: GitPrConfig,
    base_branch: str,
    head_branch: str,
    title: str,
    body: str,
    working_dir: Path,
) -> None:
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


def add_pr_labels(labels: list[str], working_dir: Path) -> None:
    LOGGER.debug("Adding PR labels: %s", labels)
    run_process_command(
        ["gh", "pr", "edit", "--add-label", ",".join(labels)],
        working_dir,
        failure_message=f"Failed to add PR labels: {', '.join(labels)}.",
        start_failure_message="Failed to start gh pr edit --add-label: {error}",
        capture_output=True,
    )


def remove_pr_labels(labels: list[str], working_dir: Path) -> None:
    LOGGER.debug("Removing PR labels: %s", labels)
    run_process_command(
        ["gh", "pr", "edit", "--remove-label", ",".join(labels)],
        working_dir,
        failure_message=f"Failed to remove PR labels: {', '.join(labels)}.",
        start_failure_message="Failed to start gh pr edit --remove-label: {error}",
        capture_output=True,
    )


def list_pr_labels(working_dir: Path) -> str:
    LOGGER.debug("Listing PR labels.")
    result = run_process_command(
        ["gh", "pr", "view", "--json", "labels"],
        working_dir,
        failure_message="Failed to list PR labels.",
        start_failure_message="Failed to start gh pr view --json labels: {error}",
        capture_output=True,
    )
    return result.stdout


def add_pr_comment(body: str, working_dir: Path) -> None:
    LOGGER.debug("Adding PR comment.")
    body_path = write_temp_text(body, prefix="propagate-pr-comment-", suffix=".txt")
    try:
        run_process_command(
            ["gh", "pr", "comment", "--body-file", str(body_path)],
            working_dir,
            failure_message="Failed to add PR comment.",
            start_failure_message="Failed to start gh pr comment: {error}",
            capture_output=True,
        )
    finally:
        cleanup_temp_file(body_path, "PR comment body file")


def list_pr_comments(working_dir: Path) -> str:
    LOGGER.debug("Listing PR comments.")
    result = run_process_command(
        ["gh", "pr", "view", "--json", "comments"],
        working_dir,
        failure_message="Failed to list PR comments.",
        start_failure_message="Failed to start gh pr view --json comments: {error}",
        capture_output=True,
    )
    return result.stdout


_FAILURE_CONCLUSIONS = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STALE"}


def poll_pr_action_checks(working_dir: Path, interval: int, timeout: int) -> tuple[str, bool]:
    LOGGER.debug("Polling PR action checks (interval=%ds, timeout=%ds).", interval, timeout)
    deadline = time.monotonic() + timeout
    while True:
        result = run_process_command(
            ["gh", "pr", "checks", "--json", "name,status,conclusion,workflow,detailsUrl"],
            working_dir,
            failure_message="Failed to fetch PR checks.",
            start_failure_message="Failed to start gh pr checks: {error}",
            capture_output=True,
        )
        try:
            all_checks = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PropagateError(f"Failed to parse PR checks output as JSON: {exc}") from exc
        filtered = [c for c in all_checks if isinstance(c.get("workflow"), dict) and c["workflow"].get("name")]
        if filtered and all(c.get("status") == "COMPLETED" for c in filtered):
            filtered_json = json.dumps(filtered)
            all_passed = not any(c.get("conclusion") in _FAILURE_CONCLUSIONS for c in filtered)
            return filtered_json, all_passed
        if time.monotonic() >= deadline:
            raise PropagateError(f"Timed out after {timeout}s waiting for PR checks to complete.")
        LOGGER.debug("PR checks not yet complete, waiting %ds.", interval)
        time.sleep(interval)
