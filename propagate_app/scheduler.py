from __future__ import annotations

from dataclasses import replace
from typing import Any

import zmq

from .constants import LOGGER
from .context_store import clear_all_context, get_context_root
from .errors import PropagateError
from .execution_flow import run_configured_execution
from .graph import build_execution_graph, build_execution_graph_adjacency
from .models import ActiveSignal, Config, ExecutionConfig, ExecutionGraph, ExecutionScheduleState, RunState, RuntimeContext
from .repo_clone import clone_single_repository
from .routing import prepare_execution_runtime_context, wrap_execution_runtime_error
from .run_state import clear_run_state, save_run_state
from .signal_reconcile import reconcile_pending_signals
from .signal_transport import publish_event_if_available, receive_signal
from .signals import signal_payload_matches_when, validate_signal_payload


def run_execution_schedule(
    config: Config,
    initial_execution_name: str,
    runtime_context: RuntimeContext,
    run_state: RunState | None = None,
    signal_socket: zmq.Socket | None = None,
    stop_after: str | None = None,
) -> None:
    execution_graph = build_execution_graph(config)
    received_signal_types: set[str] = set()
    if run_state is not None:
        received_signal_types.update(run_state.received_signal_types)
    if runtime_context.active_signal is not None:
        received_signal_types.add(runtime_context.active_signal.signal_type)
    has_prior_progress = run_state is not None and (run_state.schedule.completed_names or run_state.schedule.completed_tasks or run_state.schedule.completed_execution_phases)
    if has_prior_progress:
        LOGGER.info("Resuming execution schedule; %d executions already completed.", len(run_state.schedule.completed_names))
        schedule_state = ExecutionScheduleState(
            active_names=set(run_state.schedule.active_names),
            completed_names=set(run_state.schedule.completed_names),
            completed_tasks={name: dict(phases) for name, phases in run_state.schedule.completed_tasks.items()},
            completed_execution_phases=dict(run_state.schedule.completed_execution_phases),
        )
    else:
        schedule_state = ExecutionScheduleState(active_names=set(), completed_names=set())
        clear_all_context(get_context_root(config.config_path))
        LOGGER.info("Starting execution schedule with initial execution '%s'.", initial_execution_name)
        activate_execution_with_dependencies(config, initial_execution_name, schedule_state.active_names)
    if stop_after is not None:
        _warn_if_stop_after_unreachable(config, initial_execution_name, stop_after, schedule_state)
    current_runtime_context = runtime_context
    if run_state is not None:
        _sync_and_save(run_state, schedule_state, current_runtime_context, received_signal_types)
    reconciled_triggers: set[tuple[str, str, str]] = set()
    while True:
        if signal_socket is not None:
            current_runtime_context = _drain_incoming_signals(
                signal_socket,
                config,
                execution_graph,
                schedule_state,
                received_signal_types,
                current_runtime_context,
            )
        execution_name = select_next_runnable_execution(config, execution_graph, schedule_state)
        if execution_name is None:
            if reconcile_pending_signals(config, execution_graph, schedule_state, received_signal_types, reconciled_triggers):
                continue
            if signal_socket is not None and has_pending_signal_triggers(config, execution_graph, schedule_state, received_signal_types):
                current_runtime_context = _wait_for_signal(
                    signal_socket,
                    config,
                    execution_graph,
                    schedule_state,
                    received_signal_types,
                    current_runtime_context,
                )
                continue
            if schedule_state.completed_names == schedule_state.active_names:
                if run_state is not None:
                    clear_run_state(run_state.config_path)
                return
            remaining_names = remaining_active_execution_names(execution_graph.execution_order, schedule_state)
            raise PropagateError("No runnable executions remain for active run plan: " + ", ".join(remaining_names))
        execution = config.executions[execution_name]
        config = _ensure_repo_cloned(config, execution.repository, run_state)
        completed_task_phases = schedule_state.completed_tasks.get(execution_name, {})
        completed_execution_phase = schedule_state.completed_execution_phases.get(execution_name)
        execution_runtime_context = prepare_execution_runtime_context(config, execution, current_runtime_context)

        def on_phase_completed(exec_name: str, task_id: str, phase: str) -> None:
            if task_id:
                schedule_state.completed_tasks.setdefault(exec_name, {})[task_id] = phase
            else:
                schedule_state.completed_execution_phases[exec_name] = phase
            if run_state is not None:
                _sync_and_save(run_state, schedule_state, current_runtime_context, received_signal_types)

        try:
            current_runtime_context = run_configured_execution(
                execution,
                execution_runtime_context,
                completed_task_phases,
                on_phase_completed,
                completed_execution_phase,
                lambda updated_context: _sync_and_save(run_state, schedule_state, updated_context, received_signal_types)
                if run_state is not None else None,
            )
        except PropagateError as error:
            raise wrap_execution_runtime_error(execution, error) from error
        schedule_state.completed_names.add(execution.name)
        activate_matching_triggers(
            config,
            execution_graph,
            execution.name,
            current_runtime_context.active_signal,
            schedule_state.active_names,
            schedule_state.completed_names,
        )
        if run_state is not None:
            _sync_and_save(run_state, schedule_state, current_runtime_context, received_signal_types)
        if stop_after is not None and execution.name == stop_after:
            LOGGER.info("Stopping after execution '%s' as requested by --stop-after.", execution.name)
            return


def _ensure_repo_cloned(config: Config, repo_name: str, run_state: RunState | None) -> Config:
    repo = config.repositories[repo_name]
    if repo.url is None or repo.path is not None:
        return config
    existing_path = run_state.cloned_repos.get(repo_name) if run_state is not None else None
    cloned_path = clone_single_repository(repo_name, repo, existing_path, config.clone_dir)
    if run_state is not None:
        run_state.cloned_repos[repo_name] = cloned_path
        save_run_state(run_state)
    updated_repos = {**config.repositories, repo_name: replace(repo, path=cloned_path)}
    return replace(config, repositories=updated_repos)


def _sync_and_save(
    run_state: RunState,
    schedule_state: ExecutionScheduleState,
    runtime_context: RuntimeContext,
    received_signal_types: set[str] | None = None,
) -> None:
    run_state.schedule = ExecutionScheduleState(
        active_names=set(schedule_state.active_names),
        completed_names=set(schedule_state.completed_names),
        completed_tasks={name: dict(phases) for name, phases in schedule_state.completed_tasks.items()},
        completed_execution_phases=dict(schedule_state.completed_execution_phases),
    )
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
    active_execution_names: set[str],
    completed_execution_names: set[str],
) -> None:
    LOGGER.info("Evaluating propagation triggers after execution '%s'.", completed_execution_name)
    for trigger in execution_graph.triggers_by_after[completed_execution_name]:
        if trigger.on_signal is not None:
            if active_signal is None or trigger.on_signal != active_signal.signal_type:
                continue
            if not signal_payload_matches_when(active_signal.payload, trigger.when):
                continue
        if trigger.run in completed_execution_names:
            LOGGER.info("Skipping activation of '%s' because it already completed in this run.", trigger.run)
            continue
        if trigger.run in active_execution_names:
            LOGGER.info("Skipping activation of '%s' because it is already active.", trigger.run)
            continue
        LOGGER.info("Matched propagation trigger after '%s': activate '%s'.", trigger.after, trigger.run)
        activate_execution_with_dependencies(config, trigger.run, active_execution_names)


def activate_execution_with_dependencies(
    config: Config,
    execution_name: str,
    active_execution_names: set[str],
) -> None:
    execution = config.executions[execution_name]
    for dependency_name in execution.depends_on:
        if dependency_name not in active_execution_names:
            LOGGER.info("Activating dependency '%s' for execution '%s'.", dependency_name, execution_name)
        activate_execution_with_dependencies(config, dependency_name, active_execution_names)
    if execution_name in active_execution_names:
        return
    LOGGER.info("Activating execution '%s'.", execution_name)
    active_execution_names.add(execution_name)


def select_next_runnable_execution(
    config: Config,
    execution_graph: ExecutionGraph,
    schedule_state: ExecutionScheduleState,
) -> str | None:
    runnable_names = [
        execution_name
        for execution_name in execution_graph.execution_order
        if execution_is_runnable(config.executions[execution_name], schedule_state)
    ]
    if not runnable_names:
        return None
    if len(runnable_names) > 1:
        LOGGER.info("Multiple runnable executions available (%s); selecting '%s' by config order.", ", ".join(runnable_names), runnable_names[0])
    return runnable_names[0]


def remaining_active_execution_names(
    execution_order: tuple[str, ...],
    schedule_state: ExecutionScheduleState,
) -> list[str]:
    return [
        execution_name
        for execution_name in execution_order
        if execution_name in schedule_state.active_names and execution_name not in schedule_state.completed_names
    ]


def execution_is_runnable(execution: ExecutionConfig, schedule_state: ExecutionScheduleState) -> bool:
    if execution.name not in schedule_state.active_names or execution.name in schedule_state.completed_names:
        return False
    return all(dependency_name in schedule_state.completed_names for dependency_name in execution.depends_on)


def has_pending_signal_triggers(
    config: Config,
    execution_graph: ExecutionGraph,
    schedule_state: ExecutionScheduleState,
    received_signal_types: set[str],
) -> bool:
    return bool(_pending_signal_types(execution_graph, schedule_state, received_signal_types))


def _drain_incoming_signals(
    signal_socket: zmq.Socket,
    config: Config,
    execution_graph: ExecutionGraph,
    schedule_state: ExecutionScheduleState,
    received_signal_types: set[str],
    runtime_context: RuntimeContext,
) -> RuntimeContext:
    current_runtime_context = runtime_context
    while True:
        result = receive_signal(signal_socket, block=False)
        if result is None:
            return current_runtime_context
        active_signal = _process_received_signal(result, config, execution_graph, schedule_state, received_signal_types)
        if active_signal is not None:
            current_runtime_context = replace(current_runtime_context, active_signal=active_signal)


def _wait_for_signal(
    signal_socket: zmq.Socket,
    config: Config,
    execution_graph: ExecutionGraph,
    schedule_state: ExecutionScheduleState,
    received_signal_types: set[str],
    runtime_context: RuntimeContext,
) -> RuntimeContext:
    pending = _pending_signal_types(execution_graph, schedule_state, received_signal_types)
    LOGGER.info("Waiting for external signal (%s)...", ", ".join(sorted(pending)))
    publish_event_if_available(runtime_context.pub_socket, "waiting_for_signal", {
        "execution": "",
        "task_id": "",
        "signal": ", ".join(sorted(pending)),
        "metadata": runtime_context.metadata,
    })
    while True:
        result = receive_signal(signal_socket, block=True, timeout_ms=1000)
        if result is None:
            continue
        active_signal = _process_received_signal(result, config, execution_graph, schedule_state, received_signal_types)
        new_pending = _pending_signal_types(execution_graph, schedule_state, received_signal_types)
        if new_pending != pending:
            signal_type, _ = result
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
    result: tuple[str, dict[str, Any]],
    config: Config,
    execution_graph: ExecutionGraph,
    schedule_state: ExecutionScheduleState,
    received_signal_types: set[str],
) -> ActiveSignal | None:
    signal_type, payload = result
    if signal_type not in config.signals:
        LOGGER.warning("Received unknown signal '%s'; ignoring.", signal_type)
        return None
    signal_config = config.signals[signal_type]
    try:
        validate_signal_payload(signal_config, payload)
    except PropagateError as error:
        LOGGER.warning("Received signal '%s' with invalid payload: %s; ignoring.", signal_type, error)
        return None
    LOGGER.info("Received external signal '%s'.", signal_type)
    received_signal_types.add(signal_type)
    active_signal = ActiveSignal(signal_type=signal_type, payload=payload, source="external")
    for completed_name in list(schedule_state.completed_names):
        activate_matching_triggers(
            config,
            execution_graph,
            completed_name,
            active_signal,
            schedule_state.active_names,
            schedule_state.completed_names,
        )
    return active_signal


def _pending_signal_types(
    execution_graph: ExecutionGraph,
    schedule_state: ExecutionScheduleState,
    received_signal_types: set[str],
) -> set[str]:
    pending = set()
    for completed_name in schedule_state.completed_names:
        for trigger in execution_graph.triggers_by_after[completed_name]:
            if trigger.on_signal is None:
                continue
            if trigger.run in schedule_state.completed_names or trigger.run in schedule_state.active_names:
                continue
            # Triggers with 'when' stay pending even after receiving the signal type,
            # because the payload may not have matched. Only triggers without 'when'
            # are satisfied by any reception of their signal type.
            if trigger.when is None and trigger.on_signal in received_signal_types:
                continue
            pending.add(trigger.on_signal)
    return pending


def _warn_if_stop_after_unreachable(
    config: Config,
    initial_execution_name: str,
    stop_after: str,
    schedule_state: ExecutionScheduleState,
) -> None:
    if stop_after in schedule_state.active_names:
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
