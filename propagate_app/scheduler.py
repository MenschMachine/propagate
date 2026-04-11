from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import zmq

from .constants import LOGGER
from .context_refs import coerce_context_condition, resolve_context_ref_dir
from .context_store import clear_all_context, get_context_root, get_execution_context_dir
from .errors import AgentInterrupted, PropagateError
from .execution_flow import run_configured_execution
from .graph import build_execution_graph, build_execution_graph_adjacency
from .models import ActiveSignal, Config, ExecutionConfig, ExecutionGraph, ExecutionStatus, RunState, RuntimeContext, TaskStatus
from .repo_clone import clone_single_repository
from .routing import prepare_execution_runtime_context, wrap_execution_runtime_error
from .run_state import save_run_state
from .signal_reconcile import reconcile_pending_signals
from .signal_transport import publish_event_if_available, receive_message
from .signals import select_initial_execution, signal_payload_matches_when, validate_signal_payload


def _completed_names(executions: dict[str, ExecutionStatus]) -> set[str]:
    return {n for n, e in executions.items() if e.state == "completed"}


def _active_names(executions: dict[str, ExecutionStatus]) -> set[str]:
    return {n for n, e in executions.items() if e.state != "inactive"}


def run_execution_schedule(
    config: Config,
    initial_execution_name: str,
    runtime_context: RuntimeContext,
    run_state: RunState | None = None,
    signal_socket: zmq.Socket | None = None,
    stop_after: str | None = None,
    skip_executions: set[str] | None = None,
    skip_tasks: dict[str, set[str]] | None = None,
    on_entry_signal: Callable[[ExecutionConfig, ActiveSignal, dict], None] | None = None,
) -> None:
    execution_graph = build_execution_graph(config)
    received_signal_types: set[str] = set()
    if run_state is not None:
        received_signal_types.update(run_state.received_signal_types)
    if runtime_context.active_signal is not None:
        received_signal_types.add(runtime_context.active_signal.signal_type)
    has_prior_progress = run_state is not None and any(e.state != "inactive" for e in run_state.executions.values())
    if has_prior_progress:
        completed_count = sum(1 for e in run_state.executions.values() if e.state == "completed")
        LOGGER.info("Resuming execution schedule; %d executions already completed.", completed_count)
        executions = run_state.executions
    else:
        executions = {}
        if run_state is not None:
            run_state.executions = executions
        clear_all_context(get_context_root(config.config_path))
        LOGGER.info("Starting execution schedule with initial execution '%s'.", initial_execution_name)
        activate_execution_with_dependencies(config, initial_execution_name, executions)
    if stop_after is not None:
        _warn_if_stop_after_unreachable(config, initial_execution_name, stop_after, executions)
    current_runtime_context = replace(runtime_context, signal_socket=signal_socket)
    if run_state is not None:
        _sync_and_save(run_state, current_runtime_context, received_signal_types)
    reconciled_triggers: set[tuple[str, str, str]] = set()
    while True:
        if signal_socket is not None:
            current_runtime_context = _drain_incoming_signals(
                signal_socket,
                config,
                execution_graph,
                executions,
                received_signal_types,
                current_runtime_context,
                run_state,
                on_entry_signal=on_entry_signal,
            )
        execution_name = select_next_runnable_execution(config, execution_graph, executions, skip_executions)
        if execution_name is None:
            if reconcile_pending_signals(config, execution_graph, executions, received_signal_types, reconciled_triggers):
                continue
            if signal_socket is not None and has_pending_signal_triggers(config, execution_graph, executions, received_signal_types):
                current_runtime_context = _wait_for_signal(
                    signal_socket,
                    config,
                    execution_graph,
                    executions,
                    received_signal_types,
                    current_runtime_context,
                    run_state,
                    on_entry_signal=on_entry_signal,
                )
                continue
            completed = _completed_names(executions)
            active = _active_names(executions)
            remaining = active - completed
            if not remaining or _all_blocked_by_skip(remaining, skip_executions, config):
                return
            remaining_names = remaining_active_execution_names(execution_graph.execution_order, executions)
            raise PropagateError("No runnable executions remain for active run plan: " + ", ".join(remaining_names))
        execution = config.executions[execution_name]
        config = _ensure_repo_cloned(config, execution.repository, run_state)
        execution_status = executions.setdefault(execution_name, ExecutionStatus())
        execution_status.state = "in_progress"
        execution_runtime_context = prepare_execution_runtime_context(config, execution, current_runtime_context)

        def on_phase_completed(exec_name: str, task_id: str, phase: str) -> None:
            es = executions.setdefault(exec_name, ExecutionStatus())
            if task_id:
                ts = es.tasks.setdefault(task_id, TaskStatus())
                if phase == "before":
                    ts.phases.before_completed = True
                elif phase == "agent":
                    ts.phases.agent_completed = True
                elif phase == "after":
                    ts.phases.after_completed = True
            else:
                if phase == "before":
                    es.before_completed = True
                elif phase == "after":
                    es.after_completed = True
            if run_state is not None:
                _sync_and_save(run_state, current_runtime_context, received_signal_types)

        def on_tasks_reset(exec_name: str, task_ids: list[str]) -> None:
            es = executions.get(exec_name)
            if es is not None:
                for task_id in task_ids:
                    es.tasks.pop(task_id, None)
            if run_state is not None:
                _sync_and_save(run_state, current_runtime_context, received_signal_types)

        try:
            current_runtime_context = run_configured_execution(
                execution,
                execution_runtime_context,
                execution_status,
                on_phase_completed,
                lambda updated_context: _sync_and_save(run_state, updated_context, received_signal_types)
                if run_state is not None else None,
                on_tasks_reset,
                skip_task_ids=skip_tasks.get(execution.name) if skip_tasks else None,
            )
        except AgentInterrupted:
            raise
        except PropagateError as error:
            raise wrap_execution_runtime_error(execution, error) from error
        executions[execution.name].state = "completed"
        activate_matching_triggers(
            config,
            execution_graph,
            execution.name,
            current_runtime_context.active_signal,
            executions,
            run_state.activated_triggers if run_state is not None else None,
        )
        if run_state is not None:
            _sync_and_save(run_state, current_runtime_context, received_signal_types)
        if stop_after is not None and execution.name == stop_after:
            LOGGER.info("Stopping after execution '%s' as requested by --stop-after.", execution.name)
            return


def _ensure_repo_cloned(config: Config, repo_name: str, run_state: RunState | None) -> Config:
    repo = config.repositories[repo_name]
    if repo.url is None or repo.path is not None:
        return config
    existing_path = run_state.cloned_repos.get(repo_name) if run_state is not None else None
    cloned_path = clone_single_repository(
        repo_name,
        repo,
        existing_path,
        config.clone_dir,
        project_name=config.config_path.stem,
        repo_cache_dir=config.repo_cache_dir,
    )
    if run_state is not None:
        run_state.cloned_repos[repo_name] = cloned_path
        save_run_state(run_state)
    updated_repos = {**config.repositories, repo_name: replace(repo, path=cloned_path)}
    return replace(config, repositories=updated_repos)


def _sync_and_save(
    run_state: RunState,
    runtime_context: RuntimeContext,
    received_signal_types: set[str] | None = None,
) -> None:
    run_state.active_signal = runtime_context.active_signal
    run_state.initialized_signal_context_dirs = set(runtime_context.initialized_signal_context_dirs)
    if received_signal_types is not None:
        run_state.received_signal_types = set(received_signal_types)
    save_run_state(run_state)


def activate_matching_triggers(
    config: Config,
    execution_graph: ExecutionGraph,
    completed_execution_name: str,
    active_signal: ActiveSignal | None,
    executions: dict[str, ExecutionStatus],
    activated_triggers: set[tuple[str, str | None, str]] | None = None,
) -> None:
    """Evaluate propagation triggers after an execution completes.

    Mutates ``executions`` (activates new executions) and ``activated_triggers``
    (records which trigger edges have fired).
    """
    LOGGER.info("Evaluating propagation triggers after execution '%s'.", completed_execution_name)
    context_dir = get_execution_context_dir(get_context_root(config.config_path), completed_execution_name)
    completed = _completed_names(executions)
    active = _active_names(executions)
    if activated_triggers is None:
        activated_triggers = set()
    for trigger in execution_graph.triggers_by_after[completed_execution_name]:
        trigger_key = (trigger.after, trigger.on_signal, trigger.run)
        if trigger_key in activated_triggers:
            LOGGER.debug("Skipping already activated trigger (%s, %s, %s).", trigger.after, trigger.on_signal, trigger.run)
            continue
        if trigger.when_context is not None and not _evaluate_trigger_context_gate(trigger.when_context, context_dir):
            continue
        if trigger.on_signal is not None:
            if active_signal is None or trigger.on_signal != active_signal.signal_type:
                continue
            if not signal_payload_matches_when(
                active_signal.payload,
                trigger.when,
                context_dir,
                config.signals[active_signal.signal_type],
            ):
                continue
        if trigger.run in completed:
            LOGGER.info("Skipping activation of '%s' because it already completed in this run.", trigger.run)
            continue
        if trigger.run in active:
            LOGGER.info("Skipping activation of '%s' because it is already active.", trigger.run)
            continue
        LOGGER.info("Matched propagation trigger after '%s': activate '%s'.", trigger.after, trigger.run)
        activate_execution_with_dependencies(config, trigger.run, executions)
        activated_triggers.add(trigger_key)


def _evaluate_trigger_context_gate(gate, context_dir: Path) -> bool:
    gate = coerce_context_condition(gate)
    ref_dir = resolve_context_ref_dir(
        context_dir.parent,
        context_dir.name,
        "",
        gate.ref,
    )
    key_path = ref_dir / gate.ref.key
    try:
        truthy = key_path.is_file() and key_path.read_text(encoding="utf-8") != ""
    except OSError as error:
        LOGGER.debug("Failed to read trigger context gate '%s' from %s: %s", gate, key_path, error)
        truthy = False
    except UnicodeDecodeError as error:
        LOGGER.debug("Failed to decode trigger context gate '%s' from %s as UTF-8: %s", gate, key_path, error)
        truthy = False
    return not truthy if gate.negate else truthy


def activate_execution_with_dependencies(
    config: Config,
    execution_name: str,
    executions: dict[str, ExecutionStatus],
) -> None:
    execution = config.executions[execution_name]
    for dependency_name in execution.depends_on:
        existing = executions.get(dependency_name)
        if existing is None or existing.state == "inactive":
            LOGGER.info("Activating dependency '%s' for execution '%s'.", dependency_name, execution_name)
        activate_execution_with_dependencies(config, dependency_name, executions)
    existing = executions.get(execution_name)
    if existing is not None and existing.state != "inactive":
        return
    LOGGER.info("Activating execution '%s'.", execution_name)
    executions[execution_name] = ExecutionStatus(state="pending")


def select_next_runnable_execution(
    config: Config,
    execution_graph: ExecutionGraph,
    executions: dict[str, ExecutionStatus],
    skip_executions: set[str] | None = None,
) -> str | None:
    runnable_names = [
        execution_name
        for execution_name in execution_graph.execution_order
        if execution_is_runnable(config.executions[execution_name], executions)
        and (skip_executions is None or execution_name not in skip_executions)
    ]
    if not runnable_names:
        return None
    if len(runnable_names) > 1:
        LOGGER.info("Multiple runnable executions available (%s); selecting '%s' by config order.", ", ".join(runnable_names), runnable_names[0])
    return runnable_names[0]


def remaining_active_execution_names(
    execution_order: tuple[str, ...],
    executions: dict[str, ExecutionStatus],
) -> list[str]:
    return [
        execution_name
        for execution_name in execution_order
        if execution_name in executions and executions[execution_name].state in ("pending", "in_progress")
    ]


def execution_is_runnable(execution: ExecutionConfig, executions: dict[str, ExecutionStatus]) -> bool:
    es = executions.get(execution.name)
    if es is None or es.state not in ("pending", "in_progress"):
        return False
    return all(
        executions.get(dep_name) is not None and executions[dep_name].state == "completed"
        for dep_name in execution.depends_on
    )


def has_pending_signal_triggers(
    config: Config,
    execution_graph: ExecutionGraph,
    executions: dict[str, ExecutionStatus],
    received_signal_types: set[str],
) -> bool:
    return bool(_pending_signal_types(execution_graph, executions, received_signal_types))


def _drain_incoming_signals(
    signal_socket: zmq.Socket,
    config: Config,
    execution_graph: ExecutionGraph,
    executions: dict[str, ExecutionStatus],
    received_signal_types: set[str],
    runtime_context: RuntimeContext,
    run_state: RunState | None = None,
    on_entry_signal: Callable[[ExecutionConfig, ActiveSignal, dict], None] | None = None,
) -> RuntimeContext:
    current_runtime_context = runtime_context
    while True:
        message = receive_message(signal_socket, block=False)
        if message is None:
            return current_runtime_context
        kind, name, payload, metadata = message
        if kind != "signal":
            LOGGER.debug("Ignoring non-signal message '%s' while run is active.", name)
            continue
        result = (name, payload, metadata)
        active_signal = _process_received_signal(
            result,
            config,
            execution_graph,
            executions,
            received_signal_types,
            run_state,
            on_entry_signal=on_entry_signal,
        )
        if active_signal is not None:
            current_runtime_context = replace(current_runtime_context, active_signal=active_signal)


def _wait_for_signal(
    signal_socket: zmq.Socket,
    config: Config,
    execution_graph: ExecutionGraph,
    executions: dict[str, ExecutionStatus],
    received_signal_types: set[str],
    runtime_context: RuntimeContext,
    run_state: RunState | None = None,
    on_entry_signal: Callable[[ExecutionConfig, ActiveSignal, dict], None] | None = None,
) -> RuntimeContext:
    pending = _pending_signal_types(execution_graph, executions, received_signal_types)
    LOGGER.info("Waiting for external signal (%s)...", ", ".join(sorted(pending)))
    publish_event_if_available(runtime_context.pub_socket, "waiting_for_signal", {
        "execution": "",
        "task_id": "",
        "signal": ", ".join(sorted(pending)),
        "metadata": runtime_context.metadata,
    })
    while True:
        message = receive_message(signal_socket, block=True, timeout_ms=1000)
        if message is None:
            continue
        kind, name, payload, metadata = message
        if kind != "signal":
            LOGGER.debug("Ignoring non-signal message '%s' while waiting for signal.", name)
            continue
        result = (name, payload, metadata)
        active_signal = _process_received_signal(
            result,
            config,
            execution_graph,
            executions,
            received_signal_types,
            run_state,
            on_entry_signal=on_entry_signal,
        )
        new_pending = _pending_signal_types(execution_graph, executions, received_signal_types)
        if new_pending != pending:
            signal_type, _, _ = result
            LOGGER.info("Signal '%s' satisfied; resuming execution.", signal_type)
            publish_event_if_available(runtime_context.pub_socket, "signal_received", {
                "execution": "",
                "task_id": "",
                "signal": signal_type,
                "metadata": runtime_context.metadata,
            })
            if active_signal is not None:
                return replace(runtime_context, active_signal=active_signal)
            return runtime_context


def _process_received_signal(
    result: tuple[str, dict[str, Any], dict[str, Any]],
    config: Config,
    execution_graph: ExecutionGraph,
    executions: dict[str, ExecutionStatus],
    received_signal_types: set[str],
    run_state: RunState | None = None,
    on_entry_signal: Callable[[ExecutionConfig, ActiveSignal, dict], None] | None = None,
) -> ActiveSignal | None:
    signal_type, payload, metadata = result
    if signal_type not in config.signals:
        LOGGER.info("Received unknown signal '%s'; ignoring.", signal_type)
        return None
    signal_config = config.signals[signal_type]
    try:
        validate_signal_payload(signal_config, payload)
    except PropagateError as error:
        LOGGER.warning("Received signal '%s' with invalid payload: %s; ignoring.", signal_type, error)
        return None
    active_signal = ActiveSignal(signal_type=signal_type, payload=payload, source="external")
    try:
        entry_execution = _resolve_entry_execution(config, active_signal)
    except PropagateError as error:
        LOGGER.warning("Ignoring entry signal '%s' while run is active: %s", signal_type, error)
        return None
    if entry_execution is not None:
        if on_entry_signal is not None:
            on_entry_signal(entry_execution, active_signal, dict(metadata))
            LOGGER.info("Queued entry signal '%s' while a run is already active.", signal_type)
        else:
            LOGGER.warning("Rejecting entry signal '%s' while a run is already active.", signal_type)
        return None
    LOGGER.info("Received external signal '%s'.", signal_type)
    received_signal_types.add(signal_type)
    completed = _completed_names(executions)
    activated_triggers = run_state.activated_triggers if run_state is not None else None
    for completed_name in list(completed):
        activate_matching_triggers(
            config,
            execution_graph,
            completed_name,
            active_signal,
            executions,
            activated_triggers,
        )
    return active_signal


def _resolve_entry_execution(config: Config, active_signal: ActiveSignal) -> ExecutionConfig | None:
    try:
        return select_initial_execution(config, None, active_signal)
    except PropagateError as error:
        if "No execution accepts signal" in str(error):
            return None
        raise


def _pending_signal_types(
    execution_graph: ExecutionGraph,
    executions: dict[str, ExecutionStatus],
    received_signal_types: set[str],
) -> set[str]:
    completed = _completed_names(executions)
    active = _active_names(executions)
    pending: set[str] = set()
    for completed_name in completed:
        for trigger in execution_graph.triggers_by_after[completed_name]:
            if trigger.on_signal is None:
                continue
            if trigger.run in completed or trigger.run in active:
                continue
            # Triggers with 'when' stay pending even after receiving the signal type,
            # because the payload may not have matched. Only triggers without 'when'
            # are satisfied by any reception of their signal type.
            if trigger.when is None and trigger.on_signal in received_signal_types:
                continue
            pending.add(trigger.on_signal)
    return pending


def _all_blocked_by_skip(
    remaining: set[str],
    skip_executions: set[str] | None,
    config: Config,
) -> bool:
    """Return True if every execution in *remaining* is either skipped or depends on a skipped execution."""
    if not skip_executions:
        return False
    for name in remaining:
        if name in skip_executions:
            continue
        if not _depends_on_skipped(name, skip_executions, config):
            return False
    return True


def _depends_on_skipped(name: str, skip_executions: set[str], config: Config) -> bool:
    """Return True if *name* transitively depends on any skipped execution."""
    visited: set[str] = set()
    stack = list(config.executions[name].depends_on)
    while stack:
        dep = stack.pop()
        if dep in visited:
            continue
        visited.add(dep)
        if dep in skip_executions:
            return True
        if dep in config.executions:
            stack.extend(config.executions[dep].depends_on)
    return False


def _warn_if_stop_after_unreachable(
    config: Config,
    initial_execution_name: str,
    stop_after: str,
    executions: dict[str, ExecutionStatus],
) -> None:
    if stop_after in executions and executions[stop_after].state != "inactive":
        return
    adjacency = build_execution_graph_adjacency(config.executions, config.propagation_triggers)
    reachable: set[str] = set()
    stack = [initial_execution_name]
    while stack:
        name = stack.pop()
        if name in reachable:
            continue
        reachable.add(name)
        stack.extend(adjacency.get(name, ()))
    if stop_after not in reachable:
        LOGGER.warning(
            "--stop-after execution '%s' is not reachable from '%s'; the run will complete without stopping early.",
            stop_after,
            initial_execution_name,
        )
