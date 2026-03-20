from collections.abc import Callable
from pathlib import Path

from .constants import LOGGER
from .context_store import ensure_context_dir, read_context_value, resolve_execution_context_dir, write_context_value
from .errors import PropagateError
from .git_publish import (
    add_pr_comment,
    add_pr_labels,
    create_execution_commit,
    create_pull_request,
    list_pr_comments,
    list_pr_labels,
    load_commit_message,
    poll_pr_action_checks,
    push_branch,
    remove_pr_labels,
    split_commit_message,
)
from .git_repo import (
    ensure_clean_working_tree,
    ensure_git_repository,
    get_current_branch,
    prepare_execution_branch,
    resolve_execution_branch_name,
    working_tree_has_changes,
)
from .git_templates import render_git_template
from .models import (
    GitBranchConfig,
    GitCommitConfig,
    GitConfig,
    GitPrConfig,
    GitPushConfig,
    GitRunState,
    PullRequestResult,
    PreparedGitExecution,
    RuntimeContext,
)
from .signal_transport import publish_event_if_available

_GIT_STATE_KEY_PREFIX = ":git."


def _normalize_pr_result(result: PullRequestResult | str) -> PullRequestResult:
    if isinstance(result, PullRequestResult):
        return result
    return PullRequestResult(url=result, created=True)


def _persist_git_state(runtime_context: RuntimeContext, field: str, value: str) -> None:
    context_dir = resolve_execution_context_dir(runtime_context)
    ensure_context_dir(context_dir)
    write_context_value(context_dir, f"{_GIT_STATE_KEY_PREFIX}{field}", value)


def git_do_branch(execution_name: str, git_config: GitConfig, runtime_context: RuntimeContext) -> None:
    git_state = runtime_context.git_state
    if git_state is None:
        raise PropagateError(f"Execution '{execution_name}' git:branch requires git configuration.")
    branch_config = git_config.branch
    if branch_config.name_key is not None:
        context_dir = resolve_execution_context_dir(runtime_context)
        resolved_name = read_context_value(context_dir, branch_config.name_key)
        LOGGER.debug("Resolved branch name from context key '%s': '%s'.", branch_config.name_key, resolved_name)
        branch_config = GitBranchConfig(
            name=resolved_name, base=branch_config.base, reuse=branch_config.reuse,
        )
    if branch_config.name_template is not None:
        rendered_name = render_git_template(branch_config.name_template, runtime_context)
        LOGGER.debug("Resolved branch name from template '%s': '%s'.", branch_config.name_template, rendered_name)
        branch_config = GitBranchConfig(
            name=rendered_name,
            base=branch_config.base,
            reuse=branch_config.reuse,
        )
    prepared = prepare_git_execution(
        execution_name,
        branch_config,
        git_config.push.remote if git_config.push is not None else None,
        runtime_context.working_dir,
    )
    git_state.starting_branch = prepared.starting_branch
    git_state.selected_branch = prepared.selected_branch
    _persist_git_state(runtime_context, "starting_branch", prepared.starting_branch)
    _persist_git_state(runtime_context, "selected_branch", prepared.selected_branch)


def git_do_commit(execution_name: str, git_config: GitConfig, runtime_context: RuntimeContext) -> None:
    if not working_tree_has_changes(runtime_context.working_dir):
        LOGGER.info("No repository changes detected; skipping commit.")
        return
    commit_message = load_execution_commit_message(execution_name, git_config.commit, runtime_context)
    create_execution_git_commit(execution_name, commit_message, runtime_context.working_dir)
    assert runtime_context.git_state is not None
    runtime_context.git_state.commit_message = commit_message
    _persist_git_state(runtime_context, "commit_message", commit_message)


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
    create_execution_git_pr(execution_name, git_config, prepared, commit_message, runtime_context)


def git_do_publish(execution_name: str, git_config: GitConfig, runtime_context: RuntimeContext) -> None:
    if git_config.push is None or git_config.pr is None:
        raise PropagateError(
            f"Execution '{execution_name}' git:publish requires both git.push and git.pr to be configured."
        )
    git_do_commit(execution_name, git_config, runtime_context)
    git_do_push(execution_name, git_config, runtime_context)
    git_do_pr(execution_name, git_config, runtime_context)


def prepare_git_execution(
    execution_name: str,
    branch_config: GitBranchConfig,
    remote_name: str | None,
    working_dir: Path,
) -> PreparedGitExecution:
    starting_branch = prepare_git_execution_start(execution_name, working_dir)
    selected_branch = prepare_git_execution_branch(execution_name, branch_config, remote_name, starting_branch, working_dir)
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
    remote_name: str | None,
    starting_branch: str,
    working_dir: Path,
) -> str:
    try:
        target_branch = resolve_execution_branch_name(branch_config, execution_name, working_dir)
        return prepare_execution_branch(
            target_branch,
            branch_config.base or starting_branch,
            remote_name,
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


def load_pr_title_body(pr_config: GitPrConfig, commit_message: str, runtime_context: RuntimeContext) -> tuple[str, str]:
    title, body = split_commit_message(commit_message)
    if (
        pr_config.title_key is None
        and pr_config.body_key is None
        and pr_config.title_template is None
        and pr_config.body_template is None
    ):
        return title, body
    context_dir = resolve_execution_context_dir(runtime_context)
    if pr_config.title_key is not None:
        title = read_context_value(context_dir, pr_config.title_key)
        LOGGER.debug("Loaded PR title from context key '%s'.", pr_config.title_key)
    elif pr_config.title_template is not None:
        title = render_git_template(pr_config.title_template, runtime_context)
        LOGGER.debug("Rendered PR title from template '%s'.", pr_config.title_template)
    if pr_config.body_key is not None:
        body = read_context_value(context_dir, pr_config.body_key)
        LOGGER.debug("Loaded PR body from context key '%s'.", pr_config.body_key)
    elif pr_config.body_template is not None:
        body = render_git_template(pr_config.body_template, runtime_context)
        LOGGER.debug("Rendered PR body from template '%s'.", pr_config.body_template)
    return title, body


def create_execution_git_pr(
    execution_name: str,
    git_config: GitConfig,
    prepared_execution: PreparedGitExecution,
    commit_message: str,
    runtime_context: RuntimeContext,
) -> None:
    if git_config.pr is None:
        return
    try:
        title, body = load_pr_title_body(git_config.pr, commit_message, runtime_context)
        pr_result = _normalize_pr_result(create_pull_request(
            git_config.pr,
            git_config.pr.base or git_config.branch.base or prepared_execution.starting_branch,
            prepared_execution.selected_branch,
            title,
            body,
            runtime_context.working_dir,
        ))
        pr_url = pr_result.url
        if pr_url:
            event_type = "pr_created" if pr_result.created else "pr_updated"
            publish_event_if_available(runtime_context.pub_socket, event_type, {
                "execution": execution_name,
                "pr_url": pr_url,
                "metadata": runtime_context.metadata,
            })
        if git_config.pr.number_key is not None and pr_url:
            pr_number = pr_url.rstrip("/").split("/")[-1]
            if not pr_number.isdigit():
                raise PropagateError(f"Could not extract PR number from URL '{pr_url}'.")
            context_dir = resolve_execution_context_dir(runtime_context)
            ensure_context_dir(context_dir)
            write_context_value(context_dir, git_config.pr.number_key, pr_number)
            LOGGER.debug("Stored PR number '%s' to context key '%s'.", pr_number, git_config.pr.number_key)
    except PropagateError as error:
        raise wrap_execution_git_phase_error(execution_name, "PR creation", error) from error


def _run_pr_interaction(execution_name: str, phase: str, runtime_context: RuntimeContext, action: Callable[[Path, Path], None]) -> None:
    context_dir = resolve_execution_context_dir(runtime_context)
    try:
        action(context_dir, runtime_context.working_dir)
    except PropagateError as error:
        raise wrap_execution_git_phase_error(execution_name, phase, error) from error


def resolve_label_args(args: list[str], context_dir: Path) -> list[str]:
    resolved: list[str] = []
    for arg in args:
        if arg.startswith(":"):
            value = read_context_value(context_dir, arg)
            validate_resolved_label(value, arg)
            resolved.append(value)
        else:
            resolved.append(arg)
    return resolved


def validate_resolved_label(value: str, key: str) -> None:
    stripped = value.strip()
    if not stripped:
        raise PropagateError(f"Context key '{key}' resolved to an empty label.")
    if "\n" in stripped or "," in stripped:
        raise PropagateError(f"Context key '{key}' resolved to a label containing invalid characters (commas or newlines).")


def git_do_pr_labels_add(execution_name: str, args: list[str], runtime_context: RuntimeContext) -> None:
    def action(context_dir: Path, working_dir: Path) -> None:
        labels = resolve_label_args(args, context_dir)
        add_pr_labels(labels, working_dir)
    _run_pr_interaction(execution_name, "PR label add", runtime_context, action)


def git_do_pr_labels_remove(execution_name: str, args: list[str], runtime_context: RuntimeContext) -> None:
    def action(context_dir: Path, working_dir: Path) -> None:
        labels = resolve_label_args(args, context_dir)
        remove_pr_labels(labels, working_dir)
    _run_pr_interaction(execution_name, "PR label remove", runtime_context, action)


def git_do_pr_labels_list(execution_name: str, store_key: str, runtime_context: RuntimeContext) -> None:
    def action(context_dir: Path, working_dir: Path) -> None:
        output = list_pr_labels(working_dir)
        ensure_context_dir(context_dir)
        write_context_value(context_dir, store_key, output)
        LOGGER.debug("Stored PR labels JSON to context key '%s'.", store_key)
    _run_pr_interaction(execution_name, "PR labels list", runtime_context, action)


def git_do_pr_comment_add(execution_name: str, body_key: str, runtime_context: RuntimeContext) -> None:
    def action(context_dir: Path, working_dir: Path) -> None:
        body = read_context_value(context_dir, body_key)
        add_pr_comment(body, working_dir)
    _run_pr_interaction(execution_name, "PR comment add", runtime_context, action)


def git_do_pr_comments_list(execution_name: str, store_key: str, runtime_context: RuntimeContext) -> None:
    def action(context_dir: Path, working_dir: Path) -> None:
        output = list_pr_comments(working_dir)
        ensure_context_dir(context_dir)
        write_context_value(context_dir, store_key, output)
        LOGGER.debug("Stored PR comments JSON to context key '%s'.", store_key)
    _run_pr_interaction(execution_name, "PR comments list", runtime_context, action)


def git_do_pr_checks_wait(execution_name: str, store_key: str, status_key: str, interval: int, timeout: int, runtime_context: RuntimeContext) -> None:
    def action(context_dir: Path, working_dir: Path) -> None:
        filtered_json, all_passed = poll_pr_action_checks(working_dir, interval, timeout)
        ensure_context_dir(context_dir)
        write_context_value(context_dir, store_key, filtered_json)
        LOGGER.debug("Stored PR checks JSON to context key '%s'.", store_key)
        status_value = "true" if all_passed else ""
        write_context_value(context_dir, status_key, status_value)
        LOGGER.debug("Stored PR checks status '%s' to context key '%s'.", status_value, status_key)
    _run_pr_interaction(execution_name, "PR checks wait", runtime_context, action)


def cannot_start_execution_git_automation(execution_name: str, error: PropagateError) -> PropagateError:
    return PropagateError(f"Execution '{execution_name}' cannot start git automation: {normalize_error_message(str(error))}.")


def wrap_execution_git_phase_error(execution_name: str, phase: str, error: PropagateError) -> PropagateError:
    return PropagateError(f"Execution '{execution_name}' failed during {phase}: {normalize_error_message(str(error))}.")


def restore_git_run_state(runtime_context: RuntimeContext) -> GitRunState:
    context_dir = resolve_execution_context_dir(runtime_context)
    git_state = GitRunState()
    for field in ("starting_branch", "selected_branch", "commit_message"):
        key = f"{_GIT_STATE_KEY_PREFIX}{field}"
        try:
            value = read_context_value(context_dir, key)
            setattr(git_state, field, value)
        except PropagateError as exc:
            LOGGER.debug("Could not restore git field '%s': %s", field, exc)
    if git_state.selected_branch is not None:
        LOGGER.debug("Restored git state from context: branch '%s'.", git_state.selected_branch)
    return git_state


def normalize_error_message(message: str) -> str:
    return message.rstrip().rstrip(".")
