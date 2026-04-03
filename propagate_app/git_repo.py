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
        [
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            ".",
            ":!**/.propagate-state-*.yaml",
            ":!.env",
            ":!**/.env",
            ":!.propagate-clone",
            ":!**/.propagate-clone",
        ],
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
    remote_name: str | None,
    reuse_branch: bool,
    starting_branch: str,
    working_dir: Path,
) -> str:
    if target_branch == starting_branch:
        LOGGER.info("Using already checked out branch '%s'.", target_branch)
        sync_existing_branch(target_branch, remote_name, working_dir)
        return target_branch
    if local_branch_exists(target_branch, working_dir):
        if not reuse_branch:
            raise PropagateError(f"Git branch '{target_branch}' already exists and reuse is disabled.")
        LOGGER.info("Checking out existing branch '%s'.", target_branch)
        checkout_branch(target_branch, working_dir)
        sync_existing_branch(target_branch, remote_name, working_dir)
        return target_branch
    resolved_base_ref = resolve_branch_base_ref(base_ref, remote_name, working_dir)
    ensure_git_ref_exists(resolved_base_ref, working_dir)
    LOGGER.info("Creating and checking out branch '%s' from '%s'.", target_branch, resolved_base_ref)
    run_git_command(
        ["checkout", "-b", target_branch, resolved_base_ref],
        working_dir,
        failure_message=f"Failed to create branch '{target_branch}' from '{resolved_base_ref}'.",
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


def resolve_branch_base_ref(base_ref: str, remote_name: str | None, working_dir: Path) -> str:
    if remote_name is None:
        return base_ref
    LOGGER.info("Fetching latest '%s' from remote '%s' before branch creation.", base_ref, remote_name)
    fetch = run_git_command(
        ["fetch", remote_name, base_ref],
        working_dir,
        failure_message=f"Failed to fetch base ref '{base_ref}' from remote '{remote_name}'.",
        start_failure_message=f"Failed to start fetch of base ref '{base_ref}' from '{remote_name}': {{error}}",
        check=False,
    )
    if fetch.returncode != 0:
        if local_branch_exists(base_ref, working_dir):
            LOGGER.warning(
                "Git base ref '%s' could not be fetched from remote '%s'; falling back to local '%s'.",
                base_ref,
                remote_name,
                base_ref,
            )
            return base_ref
        raise PropagateError(f"Git base ref '{base_ref}' could not be fetched from remote '{remote_name}'.")
    return f"{remote_name}/{base_ref}"


def checkout_branch(branch_name: str, working_dir: Path) -> None:
    run_git_command(
        ["checkout", branch_name],
        working_dir,
        failure_message=f"Failed to checkout branch '{branch_name}'.",
        start_failure_message=f"Failed to start branch checkout for '{branch_name}': {{error}}",
    )


def sync_existing_branch(branch_name: str, remote_name: str | None, working_dir: Path) -> None:
    if remote_name is None:
        return
    LOGGER.info("Fetching latest '%s' from remote '%s' before reusing branch.", branch_name, remote_name)
    fetch = run_git_command(
        ["fetch", remote_name, branch_name],
        working_dir,
        failure_message=f"Failed to fetch branch '{branch_name}' from remote '{remote_name}'.",
        start_failure_message=f"Failed to start fetch of branch '{branch_name}' from '{remote_name}': {{error}}",
        check=False,
    )
    if fetch.returncode != 0:
        LOGGER.warning(
            "Git branch '%s' could not be fetched from remote '%s'; continuing with local branch.",
            branch_name,
            remote_name,
        )
        return

    ahead_count, behind_count = get_branch_divergence(branch_name, f"{remote_name}/{branch_name}", working_dir)
    if ahead_count == 0 and behind_count == 0:
        LOGGER.info("Existing branch '%s' is already up to date with '%s/%s'.", branch_name, remote_name, branch_name)
        return
    if ahead_count == 0 and behind_count > 0:
        LOGGER.info("Fast-forwarding existing branch '%s' to '%s/%s'.", branch_name, remote_name, branch_name)
        run_git_command(
            ["merge", "--ff-only", f"{remote_name}/{branch_name}"],
            working_dir,
            failure_message=f"Failed to fast-forward branch '{branch_name}' to '{remote_name}/{branch_name}'.",
            start_failure_message=f"Failed to start fast-forward for branch '{branch_name}': {{error}}",
        )
        return
    if ahead_count > 0 and behind_count == 0:
        raise PropagateError(
            f"Existing branch '{branch_name}' has {ahead_count} local commit(s) not on '{remote_name}/{branch_name}'. "
            "Push, reset, or delete the local branch before starting a new execution."
        )
    raise PropagateError(
        f"Existing branch '{branch_name}' has diverged from '{remote_name}/{branch_name}' "
        f"({ahead_count} local-only, {behind_count} remote-only commit(s)). "
        "Reconcile the branch before starting a new execution."
    )


def get_branch_divergence(local_ref: str, remote_ref: str, working_dir: Path) -> tuple[int, int]:
    result = run_git_command(
        ["rev-list", "--left-right", "--count", f"{local_ref}...{remote_ref}"],
        working_dir,
        failure_message=f"Failed to compare branch '{local_ref}' with '{remote_ref}'.",
        start_failure_message="Failed to start git rev-list for branch divergence: {error}",
        capture_output=True,
    )
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        raise PropagateError(f"Unexpected divergence output while comparing '{local_ref}' and '{remote_ref}'.")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError as error:
        raise PropagateError(f"Unexpected divergence output while comparing '{local_ref}' and '{remote_ref}'.") from error
