from pathlib import Path

from .constants import LOGGER
from .errors import PropagateError
from .models import GitBranchConfig
from .processes import run_git_command


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
        ["status", "--porcelain", "--untracked-files=all", "--", ".", ":!**/.propagate-state-*.yaml"],
        working_dir,
        failure_message="Failed to inspect git working tree status.",
        start_failure_message="Failed to start git status inspection: {error}",
        capture_output=True,
    )
    return bool(result.stdout.strip())


def resolve_execution_branch_name(branch_config: GitBranchConfig, execution_name: str, working_dir: Path) -> str:
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
    return run_git_command(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        working_dir,
        failure_message=f"Failed to inspect whether branch '{branch_name}' exists.",
        start_failure_message=f"Failed to start branch inspection for '{branch_name}': {{error}}",
        check=False,
    ).returncode == 0


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
