import json
import time
from pathlib import Path

from .constants import LOGGER
from .context_sources import run_context_source
from .context_store import read_context_value, resolve_execution_context_dir
from .errors import PropagateError
from .git_templates import render_git_template
from .models import GitCommitConfig, GitPrConfig, GitPushConfig, PullRequestResult, RuntimeContext
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
    elif commit_config.message_template is not None:
        LOGGER.info("Rendering commit message from template.")
        message = render_git_template(commit_config.message_template, runtime_context)
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
        ["add", "-A", "."],
        working_dir,
        failure_message="Failed to stage execution changes for commit.",
        start_failure_message="Failed to start git add for execution changes: {error}",
    )
    _unstage_env_files(working_dir)
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


def _unstage_env_files(working_dir: Path) -> None:
    """Remove any .env files from the staging area (safety net for repos without .gitignore coverage)."""
    result = run_git_command(
        ["diff", "--cached", "--name-only"],
        working_dir,
        failure_message="Failed to list staged files.",
        start_failure_message="Failed to start git diff --cached: {error}",
    )
    env_files = [f for f in result.stdout.splitlines() if f == ".env" or f.endswith("/.env")]
    if env_files:
        LOGGER.debug("Unstaging .env files from commit: %s", env_files)
        run_git_command(
            ["reset", "HEAD", "--", *env_files],
            working_dir,
            failure_message="Failed to unstage .env files.",
            start_failure_message="Failed to start git reset for .env files: {error}",
        )


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
    original_stderr = (result.stderr or "").strip()
    original_message = (
        f"Initial push of branch '{branch_name}' to remote '{push_config.remote}' failed"
        + (f": {original_stderr}" if original_stderr else ".")
    )
    _rebase_and_retry_push(push_config, branch_name, working_dir, original_message=original_message)


def _rebase_and_retry_push(
    push_config: GitPushConfig,
    branch_name: str,
    working_dir: Path,
    *,
    original_message: str | None = None,
) -> None:
    remote = push_config.remote
    fetch = run_git_command(
        ["fetch", remote, branch_name],
        working_dir,
        failure_message=f"Failed to fetch '{branch_name}' from remote '{remote}'.",
        start_failure_message=f"Failed to start fetch from remote '{remote}': {{error}}",
        check=False,
    )
    if fetch.returncode != 0:
        detail = f"Failed to fetch '{branch_name}' from '{remote}' before retrying push."
        if original_message:
            detail = f"{original_message} Retry failed because {detail[0].lower()}{detail[1:]}"
        raise PropagateError(detail)
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
        detail = (
            f"Failed to push branch '{branch_name}' to remote '{remote}': "
            f"push was rejected and rebase onto '{remote}/{branch_name}' failed due to conflicts."
        )
        if original_message:
            detail = f"{original_message} Retry failed because rebase onto '{remote}/{branch_name}' hit conflicts."
        raise PropagateError(detail)
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
) -> PullRequestResult:
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
        result = run_process_command(
            command,
            working_dir,
            failure_message=f"Failed to create pull request for branch '{head_branch}'.",
            start_failure_message="Failed to start pull request creation: {error}",
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").lower()
            # Heuristic: gh outputs "already exists" when a PR is open for this branch.
            # This depends on gh's English error message wording.
            if "already exists" in stderr:
                LOGGER.info("Pull request already exists for branch '%s'; skipping creation.", head_branch)
                return PullRequestResult(url=_get_existing_pr_url(working_dir), created=False)
            raise PropagateError(f"Failed to create pull request for branch '{head_branch}'. stderr: {result.stderr}")
        return PullRequestResult(url=result.stdout.strip(), created=True)
    finally:
        cleanup_temp_file(body_path, "pull request body file")


def _get_existing_pr_url(working_dir: Path) -> str:
    result = run_process_command(
        ["gh", "pr", "view", "--json", "url", "--jq", ".url"],
        working_dir,
        failure_message="Failed to get existing PR URL.",
        start_failure_message="Failed to start gh pr view: {error}",
        capture_output=True,
    )
    return result.stdout.strip()


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


_FAILURE_BUCKETS = {"fail", "cancel"}
_PENDING_BUCKET = "pending"


def _format_check_wait_target(check: dict) -> str:
    workflow_name = _extract_workflow_name(check)
    check_name = str(check.get("name") or "").strip()
    if workflow_name and check_name and workflow_name != check_name:
        return f"{workflow_name} / {check_name}"
    return workflow_name or check_name or "<unnamed check>"


def _format_check_diagnostic(check: dict) -> str:
    workflow_name = _extract_workflow_name(check)
    name = check.get("name") or "<unnamed>"
    bucket = check.get("bucket") or "<missing bucket>"
    state = check.get("state") or "<missing state>"
    if workflow_name:
        return f"{workflow_name} / {name} [bucket={bucket}, state={state}]"
    return f"{name} [bucket={bucket}, state={state}, workflow=<missing name>]"


def _extract_workflow_name(check: dict) -> str | None:
    workflow = check.get("workflow")
    if isinstance(workflow, str):
        stripped = workflow.strip()
        return stripped or None
    if isinstance(workflow, dict):
        name = workflow.get("name")
        if isinstance(name, str):
            stripped = name.strip()
            return stripped or None
    return None


def poll_pr_action_checks(working_dir: Path, interval: int, timeout: int) -> tuple[str, bool]:
    LOGGER.debug("Polling PR action checks (interval=%ds, timeout=%ds).", interval, timeout)
    deadline = time.monotonic() + timeout
    wait_message_logged = False
    while True:
        result = run_process_command(
            ["gh", "pr", "checks", "--json", "bucket,description,event,link,name,state,workflow"],
            working_dir,
            failure_message="Failed to fetch PR checks.",
            start_failure_message="Failed to start gh pr checks: {error}",
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            if result.stdout.strip():
                try:
                    all_checks = json.loads(result.stdout)
                except json.JSONDecodeError:
                    all_checks = []
            else:
                LOGGER.debug("gh pr checks exited non-zero with no output (no checks yet): %s", result.stderr.strip())
                all_checks = []
        else:
            try:
                all_checks = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise PropagateError(f"Failed to parse PR checks output as JSON: {exc}") from exc
        filtered = [c for c in all_checks if _extract_workflow_name(c)]
        if not wait_message_logged:
            LOGGER.info(
                "PR checks query returned %d total check(s); %d GitHub Actions check(s) matched.",
                len(all_checks),
                len(filtered),
            )
            if all_checks:
                diagnostics = ", ".join(_format_check_diagnostic(check) for check in all_checks[:10])
                LOGGER.info("PR checks diagnostic sample: %s", diagnostics)
                if len(all_checks) > 10:
                    LOGGER.info("PR checks diagnostic sample truncated: %d additional check(s) omitted.", len(all_checks) - 10)
        if filtered and all(c.get("bucket") != _PENDING_BUCKET for c in filtered):
            filtered_json = json.dumps(filtered)
            all_passed = not any(c.get("bucket") in _FAILURE_BUCKETS for c in filtered)
            return filtered_json, all_passed
        if filtered:
            pending_checks = sorted({
                _format_check_wait_target(check)
                for check in filtered
                if check.get("bucket") == _PENDING_BUCKET
            })
            wait_message = (
                "Waiting for PR checks to complete: " + ", ".join(pending_checks)
                if pending_checks
                else "Waiting for PR checks to report a final status."
            )
        else:
            wait_message = "Waiting for GitHub Actions PR checks to appear."
        if not wait_message_logged:
            LOGGER.info("%s", wait_message)
            wait_message_logged = True
        if time.monotonic() >= deadline:
            raise PropagateError(f"Timed out after {timeout}s waiting for PR checks to complete.")
        LOGGER.debug("PR checks not yet complete, waiting %ds.", interval)
        time.sleep(interval)
