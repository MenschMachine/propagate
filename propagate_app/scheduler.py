from .constants import LOGGER
from .context_store import clear_execution_context, get_context_root
from .errors import PropagateError
from .execution_flow import run_configured_execution
from .graph import build_execution_graph
from .models import ActiveSignal, Config, ExecutionConfig, ExecutionGraph, ExecutionScheduleState, RunState, RuntimeContext
from .routing import prepare_execution_runtime_context, wrap_execution_runtime_error
from .run_state import clear_run_state, save_run_state


def run_execution_schedule(
    config: Config,
    initial_execution_name: str,
    runtime_context: RuntimeContext,
    run_state: RunState | None = None,
) -> None:
    execution_graph = build_execution_graph(config)
    if run_state is not None and run_state.schedule.completed_names:
        LOGGER.info("Resuming execution schedule; %d executions already completed.", len(run_state.schedule.completed_names))
        schedule_state = ExecutionScheduleState(
            active_names=set(run_state.schedule.active_names),
            completed_names=set(run_state.schedule.completed_names),
        )
    else:
        schedule_state = ExecutionScheduleState(active_names=set(), completed_names=set())
        LOGGER.info("Starting execution schedule with initial execution '%s'.", initial_execution_name)
        activate_execution_with_dependencies(config, initial_execution_name, schedule_state.active_names)
    if run_state is not None:
        _sync_and_save(run_state, schedule_state, runtime_context)
    while True:
        execution_name = select_next_runnable_execution(config, execution_graph, schedule_state)
        if execution_name is None:
            if schedule_state.completed_names == schedule_state.active_names:
                if run_state is not None:
                    clear_run_state(run_state.config_path)
                return
            remaining_names = remaining_active_execution_names(execution_graph.execution_order, schedule_state)
            raise PropagateError("No runnable executions remain for active run plan: " + ", ".join(remaining_names))
        execution = config.executions[execution_name]
        context_root = get_context_root(config.config_path)
        clear_execution_context(context_root, execution.name)
        execution_runtime_context = prepare_execution_runtime_context(config, execution, runtime_context)
        try:
            run_configured_execution(execution, execution_runtime_context)
        except PropagateError as error:
            raise wrap_execution_runtime_error(execution, error) from error
        schedule_state.completed_names.add(execution.name)
        activate_matching_triggers(
            config,
            execution_graph,
            execution.name,
            runtime_context.active_signal,
            schedule_state.active_names,
            schedule_state.completed_names,
        )
        if run_state is not None:
            _sync_and_save(run_state, schedule_state, runtime_context)


def _sync_and_save(run_state: RunState, schedule_state: ExecutionScheduleState, runtime_context: RuntimeContext) -> None:
    run_state.schedule = ExecutionScheduleState(
        active_names=set(schedule_state.active_names),
        completed_names=set(schedule_state.completed_names),
    )
    run_state.initialized_signal_context_dirs = set(runtime_context.initialized_signal_context_dirs)
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
    active_signal_type = None if active_signal is None else active_signal.signal_type
    for trigger in execution_graph.triggers_by_after[completed_execution_name]:
        if trigger.on_signal is not None and trigger.on_signal != active_signal_type:
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
