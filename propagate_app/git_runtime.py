from pathlib import Path

from .constants import LOGGER
from .errors import PropagateError
from .git_publish import create_execution_commit, create_pull_request, load_commit_message, push_branch
from .git_repo import (
    ensure_clean_working_tree,
    ensure_git_repository,
    get_current_branch,
    prepare_execution_branch,
    resolve_execution_branch_name,
    working_tree_has_changes,
)
from .models import ExecutionConfig, GitBranchConfig, GitCommitConfig, GitConfig, GitPushConfig, PreparedGitExecution, RuntimeContext
from .sub_tasks import run_execution_sub_tasks


def run_execution_with_git(execution: ExecutionConfig, runtime_context: RuntimeContext) -> None:
    git_config = execution.git
    if git_config is None:
        run_execution_sub_tasks(execution, runtime_context)
        return
    LOGGER.info("Git automation enabled for execution '%s'.", execution.name)
    prepared_execution = prepare_git_execution(execution.name, git_config.branch, runtime_context.working_dir)
    run_execution_sub_tasks(execution, runtime_context)
    publish_git_execution_changes(execution, git_config, runtime_context, prepared_execution)


def prepare_git_execution(
    execution_name: str,
    branch_config: GitBranchConfig,
    working_dir: Path,
) -> PreparedGitExecution:
    starting_branch = prepare_git_execution_start(execution_name, working_dir)
    selected_branch = prepare_git_execution_branch(execution_name, branch_config, starting_branch, working_dir)
    return PreparedGitExecution(starting_branch=starting_branch, selected_branch=selected_branch)


def prepare_git_execution_start(execution_name: str, working_dir: Path) -> str:
    try:
        ensure_git_repository(working_dir)
        starting_branch = get_current_branch(working_dir)
        LOGGER.info("Detected starting branch '%s'.", starting_branch)
        ensure_clean_working_tree(working_dir)
        return starting_branch
    except PropagateError as error:
        raise cannot_start_execution_git_automation(execution_name, error) from error


def prepare_git_execution_branch(
    execution_name: str,
    branch_config: GitBranchConfig,
    starting_branch: str,
    working_dir: Path,
) -> str:
    try:
        target_branch = resolve_execution_branch_name(branch_config, execution_name, working_dir)
        return prepare_execution_branch(
            target_branch,
            branch_config.base or starting_branch,
            branch_config.reuse,
            starting_branch,
            working_dir,
        )
    except PropagateError as error:
        raise wrap_execution_git_phase_error(execution_name, "branch setup", error) from error


def publish_git_execution_changes(
    execution: ExecutionConfig,
    git_config: GitConfig,
    runtime_context: RuntimeContext,
    prepared_execution: PreparedGitExecution,
) -> None:
    if not working_tree_has_changes(runtime_context.working_dir):
        LOGGER.info("No repository changes detected after execution '%s'; skipping commit, push, and PR steps.", execution.name)
        return
    commit_message = load_execution_commit_message(execution.name, git_config.commit, runtime_context)
    create_execution_git_commit(execution.name, commit_message, runtime_context.working_dir)
    push_execution_git_branch(execution.name, git_config.push, prepared_execution.selected_branch, runtime_context.working_dir)
    create_execution_git_pr(execution.name, git_config, prepared_execution, commit_message, runtime_context.working_dir)


def load_execution_commit_message(execution_name: str, commit_config: GitCommitConfig, runtime_context: RuntimeContext) -> str:
    try:
        return load_commit_message(commit_config, runtime_context, execution_name)
    except PropagateError as error:
        raise wrap_execution_git_phase_error(execution_name, "commit-message generation", error) from error


def create_execution_git_commit(execution_name: str, commit_message: str, working_dir: Path) -> None:
    try:
        create_execution_commit(commit_message, working_dir)
    except PropagateError as error:
        raise wrap_execution_git_phase_error(execution_name, "commit creation", error) from error


def push_execution_git_branch(
    execution_name: str,
    push_config: GitPushConfig | None,
    selected_branch: str,
    working_dir: Path,
) -> None:
    if push_config is None:
        return
    try:
        push_branch(push_config, selected_branch, working_dir)
    except PropagateError as error:
        raise wrap_execution_git_phase_error(execution_name, "push", error) from error


def create_execution_git_pr(
    execution_name: str,
    git_config: GitConfig,
    prepared_execution: PreparedGitExecution,
    commit_message: str,
    working_dir: Path,
) -> None:
    if git_config.pr is None:
        return
    try:
        create_pull_request(
            git_config.pr,
            git_config.pr.base or git_config.branch.base or prepared_execution.starting_branch,
            prepared_execution.selected_branch,
            commit_message,
            working_dir,
        )
    except PropagateError as error:
        raise wrap_execution_git_phase_error(execution_name, "PR creation", error) from error


def cannot_start_execution_git_automation(execution_name: str, error: PropagateError) -> PropagateError:
    return PropagateError(f"Execution '{execution_name}' cannot start git automation: {normalize_error_message(str(error))}.")


def wrap_execution_git_phase_error(execution_name: str, phase: str, error: PropagateError) -> PropagateError:
    return PropagateError(f"Execution '{execution_name}' failed during {phase}: {normalize_error_message(str(error))}.")


def normalize_error_message(message: str) -> str:
    return message.rstrip().rstrip(".")
