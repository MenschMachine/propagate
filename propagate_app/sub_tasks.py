from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import NoReturn

from .constants import ENV_CONFIG_DIR, ENV_CONTEXT_ROOT, ENV_EXECUTION, ENV_TASK, LOGGER, PHASE_AFTER, PHASE_AGENT, PHASE_BEFORE
from .context_sources import run_context_source
from .context_store import ensure_context_dir, resolve_execution_context_dir
from .errors import PropagateError
from .git_runtime import (
    git_do_branch,
    git_do_commit,
    git_do_pr,
    git_do_pr_checks_wait,
    git_do_pr_comment_add,
    git_do_pr_comments_list,
    git_do_pr_labels_add,
    git_do_pr_labels_list,
    git_do_pr_labels_remove,
    git_do_publish,
    git_do_push,
)
from .models import ActiveSignal, ExecutionConfig, GitConfig, RuntimeContext, SubTaskConfig
from .processes import build_agent_command, run_agent_command, run_shell_command
from .prompts import build_sub_task_prompt
from .signal_context import store_active_signal_context
from .signal_transport import publish_event_if_available, receive_signal
from .signals import signal_payload_matches_when
from .temp_files import cleanup_temp_file, write_temp_text
from .validation_hooks import run_validate_hook_command


def build_context_env(runtime_context: RuntimeContext) -> dict[str, str]:
    env: dict[str, str] = {}
    env[ENV_CONTEXT_ROOT] = str(runtime_context.context_root)
    if runtime_context.config_dir != Path():
        env[ENV_CONFIG_DIR] = str(runtime_context.config_dir)
    if runtime_context.execution_name:
        env[ENV_EXECUTION] = runtime_context.execution_name
    env[ENV_TASK] = runtime_context.task_id
    return env


def run_execution_sub_tasks(
    execution: ExecutionConfig,
    runtime_context: RuntimeContext,
    completed_task_phases: dict[str, str] | None = None,
    on_phase_completed: Callable[[str, str, str], None] | None = None,
    on_runtime_context_updated: Callable[[RuntimeContext], None] | None = None,
    on_tasks_reset: Callable[[str, list[str]], None] | None = None,
) -> RuntimeContext:
    current_runtime_context = runtime_context
    task_phases = dict(completed_task_phases or {})
    task_id_to_index = {t.task_id: i for i, t in enumerate(execution.sub_tasks)}
    goto_counts: dict[str, int] = {}
    task_index = 0
    while task_index < len(execution.sub_tasks):
        sub_task = execution.sub_tasks[task_index]
        task_phase = task_phases.get(sub_task.task_id)
        if task_phase == PHASE_AFTER:
            LOGGER.info("Skipping already completed sub-task '%s' for execution '%s'.", sub_task.task_id, execution.name)
            task_index += 1
            continue
        if sub_task.when is not None and not evaluate_when_condition(sub_task.when, current_runtime_context):
            LOGGER.info("Skipping sub-task '%s' for execution '%s': 'when' condition '%s' is not met.", sub_task.task_id, execution.name, sub_task.when)
            task_index += 1
            continue
        if sub_task.wait_for_signal is not None:
            task_runtime_context = replace(current_runtime_context, task_id=sub_task.task_id)
            context_id = f"sub-task '{sub_task.task_id}'"
            run_sub_task_hook_phase(sub_task, "before", sub_task.before, task_runtime_context, execution.git, context_id)
            goto_index, current_runtime_context = _handle_wait_for_signal(
                execution,
                sub_task,
                task_id_to_index,
                current_runtime_context,
                task_phases,
                on_phase_completed,
                on_tasks_reset,
            )
            if on_runtime_context_updated is not None:
                on_runtime_context_updated(current_runtime_context)
            task_runtime_context = replace(task_runtime_context, active_signal=current_runtime_context.active_signal)
            run_sub_task_hook_phase(sub_task, "after", sub_task.after, task_runtime_context, execution.git, context_id)
            if goto_index is not None:
                task_index = goto_index
            else:
                task_index += 1
            continue
        if sub_task.goto is not None:
            count = goto_counts.get(sub_task.task_id, 0) + 1
            if count > sub_task.max_goto:
                raise PropagateError(
                    f"Sub-task '{sub_task.task_id}' in execution '{execution.name}' exceeded maximum goto count"
                    f" ({sub_task.max_goto}). Target: '{sub_task.goto}'."
                )
        run_sub_task(execution.name, sub_task, current_runtime_context, execution.git, task_phase, on_phase_completed)
        if sub_task.goto is not None:
            goto_counts[sub_task.task_id] = goto_counts.get(sub_task.task_id, 0) + 1
            goto_index = _reset_tasks_from_goto(
                execution,
                sub_task.task_id,
                sub_task.goto,
                task_id_to_index,
                task_phases,
                on_tasks_reset,
            )
            task_index = goto_index
            continue
        task_index += 1
    return current_runtime_context


def evaluate_when_condition(when: str, runtime_context: RuntimeContext) -> bool:
    negated = when.startswith("!")
    key = when[1:] if negated else when
    context_dir = resolve_execution_context_dir(runtime_context)
    key_path = context_dir / key
    truthy = key_path.is_file() and key_path.read_text(encoding="utf-8") != ""
    return not truthy if negated else truthy


def _handle_wait_for_signal(
    execution: ExecutionConfig,
    sub_task: SubTaskConfig,
    task_id_to_index: dict[str, int],
    runtime_context: RuntimeContext,
    task_phases: dict[str, str],
    on_phase_completed: Callable[[str, str, str], None] | None,
    on_tasks_reset: Callable[[str, list[str]], None] | None = None,
) -> tuple[int | None, RuntimeContext]:
    """Handle a wait_for_signal sub-task. Returns goto index or None to continue."""
    LOGGER.info(
        "Sub-task '%s' waiting for signal '%s' for execution '%s'.",
        sub_task.task_id, sub_task.wait_for_signal, execution.name,
    )
    publish_event_if_available(runtime_context.pub_socket, "waiting_for_signal", {
        "execution": execution.name,
        "task_id": sub_task.task_id,
        "signal": sub_task.wait_for_signal,
        "metadata": runtime_context.metadata,
    })
    # Block on ZMQ socket for incoming signal
    matched_route, active_signal = _wait_for_matching_signal(sub_task, runtime_context)
    updated_runtime_context = replace(runtime_context, active_signal=active_signal)

    LOGGER.info("Signal '%s' received; resuming execution '%s'.", sub_task.wait_for_signal, execution.name)
    publish_event_if_available(runtime_context.pub_socket, "signal_received", {
        "execution": execution.name,
        "task_id": sub_task.task_id,
        "signal": sub_task.wait_for_signal,
        "metadata": runtime_context.metadata,
    })

    # Mark this sub-task as completed
    if on_phase_completed is not None:
        on_phase_completed(execution.name, sub_task.task_id, PHASE_AFTER)

    if matched_route.continue_flow:
        LOGGER.info("Route matched with 'continue' for sub-task '%s'.", sub_task.task_id)
        return None, updated_runtime_context

    goto_index = _reset_tasks_from_goto(
        execution,
        sub_task.task_id,
        matched_route.goto,
        task_id_to_index,
        task_phases,
        on_tasks_reset,
    )
    return goto_index, updated_runtime_context


def _reset_tasks_from_goto(
    execution: ExecutionConfig,
    current_task_id: str,
    goto_id: str,
    task_id_to_index: dict[str, int],
    task_phases: dict[str, str],
    on_tasks_reset: Callable[[str, list[str]], None] | None = None,
) -> int:
    goto_index = task_id_to_index[goto_id]
    LOGGER.info("Route matched with 'goto: %s' (index %d) for sub-task '%s'.", goto_id, goto_index, current_task_id)
    reset_task_ids = []
    for i in range(goto_index, len(execution.sub_tasks)):
        tid = execution.sub_tasks[i].task_id
        task_phases.pop(tid, None)
        reset_task_ids.append(tid)
    if on_tasks_reset is not None:
        on_tasks_reset(execution.name, reset_task_ids)
    return goto_index


def _wait_for_matching_signal(sub_task: SubTaskConfig, runtime_context: RuntimeContext):
    """Block on the ZMQ socket waiting for a signal that matches a route."""
    signal_socket = runtime_context.signal_socket
    if signal_socket is None:
        raise PropagateError(
            f"Sub-task '{sub_task.task_id}' uses 'wait_for_signal' but no signal socket is available. "
            "Use 'propagate serve' to enable signal waiting."
        )
    signal_name = sub_task.wait_for_signal
    LOGGER.info("Waiting for signal '%s' on ZMQ socket...", signal_name)
    unmatched_count = 0
    while True:
        result = receive_signal(signal_socket, block=True, timeout_ms=1000)
        if result is None:
            continue
        received_type, payload = result
        if received_type != signal_name:
            LOGGER.debug("Received signal '%s' but waiting for '%s'; ignoring.", received_type, signal_name)
            continue
        LOGGER.info("Received signal '%s' with payload %s.", received_type, payload)
        context_dir = resolve_execution_context_dir(runtime_context)
        active_signal = ActiveSignal(signal_type=received_type, payload=payload, source="external")
        ensure_context_dir(context_dir)
        signal_config = runtime_context.signal_configs.get(signal_name)
        for route in sub_task.routes:
            if signal_payload_matches_when(payload, route.when, context_dir, signal_config):
                store_active_signal_context(context_dir, active_signal)
                return route, active_signal
        unmatched_count += 1
        LOGGER.warning(
            "Signal '%s' payload matched no route (%d unmatched so far); continuing to wait.",
            signal_name, unmatched_count,
        )


def run_sub_task(
    execution_name: str,
    sub_task: SubTaskConfig,
    runtime_context: RuntimeContext,
    git_config: GitConfig | None = None,
    completed_phase: str | None = None,
    on_phase_completed: Callable[[str, str, str], None] | None = None,
) -> None:
    LOGGER.info("Running sub-task '%s' for execution '%s'.", sub_task.task_id, execution_name)
    task_runtime_context = replace(runtime_context, task_id=sub_task.task_id)
    context_id = f"sub-task '{sub_task.task_id}'"
    skip_before = completed_phase in (PHASE_BEFORE, PHASE_AGENT)
    skip_agent = completed_phase == PHASE_AGENT
    if skip_before:
        LOGGER.info("Skipping already completed 'before' phase for sub-task '%s'.", sub_task.task_id)
    else:
        run_sub_task_hook_phase(sub_task, "before", sub_task.before, task_runtime_context, git_config, context_id)
        if on_phase_completed is not None and sub_task.before:
            on_phase_completed(execution_name, sub_task.task_id, PHASE_BEFORE)
    if skip_agent:
        LOGGER.info("Skipping already completed 'agent' phase for sub-task '%s'.", sub_task.task_id)
    elif sub_task.prompt_path is not None:
        temp_prompt_path = write_temp_text(
            build_sub_task_prompt(sub_task.prompt_path, sub_task.task_id, task_runtime_context, must_set=sub_task.must_set),
            prefix="propagate-",
            suffix=".md",
        )
        try:
            run_sub_task_agent(sub_task, temp_prompt_path, task_runtime_context)
        finally:
            cleanup_temp_file(temp_prompt_path, "temporary prompt file")
        if on_phase_completed is not None:
            on_phase_completed(execution_name, sub_task.task_id, PHASE_AGENT)
    else:
        LOGGER.debug("Sub-task '%s' has no prompt, skipping agent invocation.", sub_task.task_id)
        if on_phase_completed is not None:
            on_phase_completed(execution_name, sub_task.task_id, PHASE_AGENT)
    if sub_task.must_set:
        try:
            validate_must_set_keys(sub_task, task_runtime_context)
        except PropagateError as error:
            handle_sub_task_failure(sub_task, task_runtime_context, error)
    run_sub_task_hook_phase(sub_task, "after", sub_task.after, task_runtime_context, git_config, context_id)
    if on_phase_completed is not None:
        on_phase_completed(execution_name, sub_task.task_id, PHASE_AFTER)
    LOGGER.info("Completed sub-task '%s' for execution '%s'.", sub_task.task_id, execution_name)


def run_sub_task_hook_phase(
    sub_task: SubTaskConfig,
    phase: str,
    actions: list[str],
    runtime_context: RuntimeContext,
    git_config: GitConfig | None,
    context_id: str,
) -> None:
    try:
        run_hook_phase(context_id, phase, actions, runtime_context, git_config)
    except PropagateError as error:
        handle_sub_task_failure(sub_task, runtime_context, error, git_config)


def run_sub_task_agent(sub_task: SubTaskConfig, temp_prompt_path: Path, runtime_context: RuntimeContext) -> None:
    command = build_agent_command(runtime_context.agent_command, temp_prompt_path)
    extra_env = build_context_env(runtime_context)
    try:
        run_agent_command(command, runtime_context.working_dir, sub_task.task_id, extra_env=extra_env)
    except PropagateError as error:
        handle_sub_task_failure(sub_task, runtime_context, error)


def validate_must_set_keys(sub_task: SubTaskConfig, runtime_context: RuntimeContext) -> None:
    context_dir = resolve_execution_context_dir(runtime_context)
    missing = []
    for key in sub_task.must_set:
        key_path = context_dir / key
        if not key_path.is_file() or key_path.read_text(encoding="utf-8") == "":
            missing.append(key)
    if missing:
        raise PropagateError(
            f"Sub-task '{sub_task.task_id}' requires context keys that were not set: {', '.join(missing)}"
        )


def handle_sub_task_failure(
    sub_task: SubTaskConfig,
    runtime_context: RuntimeContext,
    error: PropagateError,
    git_config: GitConfig | None = None,
) -> NoReturn:
    if not sub_task.on_failure:
        raise error
    context_id = f"sub-task '{sub_task.task_id}'"
    try:
        run_hook_phase(context_id, "on_failure", sub_task.on_failure, runtime_context, git_config)
    except PropagateError as on_failure_error:
        raise PropagateError(f"{str(error).rstrip('.')}; {on_failure_error}") from on_failure_error
    raise error


def run_hook_phase(
    context_id: str,
    phase: str,
    actions: list[str],
    runtime_context: RuntimeContext,
    git_config: GitConfig | None = None,
) -> None:
    extra_env = build_context_env(runtime_context)
    total_actions = len(actions)
    for hook_index, action in enumerate(actions, start=1):
        if action.startswith(":"):
            source_name = action[1:]
            LOGGER.info(
                "Evaluating context source '%s' for %s hook %d/%d in %s.",
                source_name,
                phase,
                hook_index,
                total_actions,
                context_id,
            )
            run_context_source(runtime_context.context_sources[source_name], runtime_context, context_id, extra_env=extra_env)
            continue
        if action.startswith("git:"):
            LOGGER.info("Running git hook command '%s' (%s hook %d/%d) for %s.", action, phase, hook_index, total_actions, context_id)
            run_git_hook_command(action, git_config, runtime_context)
            continue
        if action.startswith("validate:"):
            LOGGER.info("Running validation hook command '%s' (%s hook %d/%d) for %s.", action, phase, hook_index, total_actions, context_id)
            run_validate_hook_command(action, runtime_context)
            continue
        LOGGER.info("Running %s hook %d/%d for %s.", phase, hook_index, total_actions, context_id)
        run_shell_command(
            action,
            runtime_context.working_dir,
            failure_message=build_hook_failure_message(phase, hook_index, context_id, "{exit_code}"),
            start_failure_message=f"Failed to start {phase} hook #{hook_index} for {context_id}: {{error}}",
            extra_env=extra_env,
        )


_PR_INTERACTION_COMMANDS = {"pr-labels-add", "pr-labels-remove", "pr-labels-list", "pr-comment-add", "pr-comments-list", "pr-checks-wait"}


def run_git_hook_command(action: str, git_config: GitConfig | None, runtime_context: RuntimeContext) -> None:
    execution_name = runtime_context.execution_name
    parts = action[4:].split()
    command = parts[0]
    args = parts[1:]
    if command not in _PR_INTERACTION_COMMANDS and git_config is None:
        raise PropagateError(f"Execution '{execution_name}' uses '{action}' but has no git configuration.")
    if command == "branch":
        git_do_branch(execution_name, git_config, runtime_context)
    elif command == "commit":
        git_do_commit(execution_name, git_config, runtime_context)
    elif command == "publish":
        git_do_publish(execution_name, git_config, runtime_context)
    elif command == "push":
        git_do_push(execution_name, git_config, runtime_context)
    elif command == "pr":
        git_do_pr(execution_name, git_config, runtime_context)
    elif command == "pr-labels-add":
        git_do_pr_labels_add(execution_name, args, runtime_context)
    elif command == "pr-labels-remove":
        git_do_pr_labels_remove(execution_name, args, runtime_context)
    elif command == "pr-labels-list":
        git_do_pr_labels_list(execution_name, args[0], runtime_context)
    elif command == "pr-comment-add":
        git_do_pr_comment_add(execution_name, args[0], runtime_context)
    elif command == "pr-comments-list":
        git_do_pr_comments_list(execution_name, args[0], runtime_context)
    elif command == "pr-checks-wait":
        interval = int(args[2]) if len(args) > 2 else 10
        timeout = int(args[3]) if len(args) > 3 else 1800
        git_do_pr_checks_wait(execution_name, args[0], args[1], interval, timeout, runtime_context)


def build_hook_failure_message(phase: str, hook_index: int, context_id: str, exit_code: int | str) -> str:
    return f"{get_hook_phase_display_name(phase)} hook #{hook_index} failed for {context_id} with exit code {exit_code}."


def get_hook_phase_display_name(phase: str) -> str:
    display_names = {"before": "Before", "after": "After", "on_failure": "on_failure"}
    return display_names.get(phase, phase)
