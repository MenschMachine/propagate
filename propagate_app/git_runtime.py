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
from .models import ExecutionConfig, GitBranchConfig, GitCommitConfig, GitConfig, GitPushConfig, GitRunState, PreparedGitExecution, RuntimeContext


def git_do_branch(execution_name: str, git_config: GitConfig, runtime_context: RuntimeContext) -> None:
    git_state = runtime_context.git_state
    if git_state is None:
        raise PropagateError(f"Execution '{execution_name}' git:branch requires git configuration.")
    prepared = prepare_git_execution(execution_name, git_config.branch, runtime_context.working_dir)
    git_state.starting_branch = prepared.starting_branch
    git_state.selected_branch = prepared.selected_branch


def git_do_commit(execution_name: str, git_config: GitConfig, runtime_context: RuntimeContext) -> None:
    if not working_tree_has_changes(runtime_context.working_dir):
        LOGGER.info("No repository changes detected; skipping commit.")
        return
    commit_message = load_execution_commit_message(execution_name, git_config.commit, runtime_context)
    create_execution_git_commit(execution_name, commit_message, runtime_context.working_dir)
    assert runtime_context.git_state is not None
    runtime_context.git_state.commit_message = commit_message


def git_do_push(execution_name: str, git_config: GitConfig, runtime_context: RuntimeContext) -> None:
    git_state = runtime_context.git_state
    if git_state is None or git_state.selected_branch is None:
        raise PropagateError(f"Execution '{execution_name}' git:push requires git:branch to have run first.")
    push_execution_git_branch(execution_name, git_config.push, git_state.selected_branch, runtime_context.working_dir)


def git_do_pr(execution_name: str, git_config: GitConfig, runtime_context: RuntimeContext) -> None:
    git_state = runtime_context.git_state
    if git_state is None or git_state.selected_branch is None:
        raise PropagateError(f"Execution '{execution_name}' git:pr requires git:branch to have run first.")
    if git_state.commit_message is None:
        LOGGER.warning("git:pr called for execution '%s' but no commit was made; the PR will point to an unchanged branch.", execution_name)
    commit_message = git_state.commit_message or load_execution_commit_message(execution_name, git_config.commit, runtime_context)
    prepared = PreparedGitExecution(
        starting_branch=git_state.starting_branch or "",
        selected_branch=git_state.selected_branch,
    )
    create_execution_git_pr(execution_name, git_config, prepared, commit_message, runtime_context.working_dir)


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
