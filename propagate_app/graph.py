from typing import Any

from .constants import LOGGER
from .errors import PropagateError
from .models import Config, ExecutionConfig, ExecutionGraph, PropagationTriggerConfig, SignalConfig
from .validation import validate_allowed_keys


def parse_propagation_triggers(
    propagation_data: Any,
    execution_names: set[str],
    signal_configs: dict[str, SignalConfig],
) -> list[PropagationTriggerConfig]:
    if propagation_data is None:
        return []
    if not isinstance(propagation_data, dict):
        raise PropagateError("Config 'propagation' must be a mapping when provided.")
    validate_allowed_keys(propagation_data, {"triggers"}, "Config 'propagation'")
    triggers_data = propagation_data.get("triggers")
    if not isinstance(triggers_data, list) or not triggers_data:
        raise PropagateError("Config 'propagation.triggers' must be a non-empty list.")
    return [
        parse_propagation_trigger(index, trigger_data, execution_names, signal_configs)
        for index, trigger_data in enumerate(triggers_data, start=1)
    ]


def parse_propagation_trigger(
    index: int,
    trigger_data: Any,
    execution_names: set[str],
    signal_configs: dict[str, SignalConfig],
) -> PropagationTriggerConfig:
    location = f"Propagation trigger #{index}"
    if not isinstance(trigger_data, dict):
        raise PropagateError(f"{location} must be a mapping.")
    validate_allowed_keys(trigger_data, {"after", "run", "on_signal", "when"}, location)
    after = trigger_data.get("after")
    run = trigger_data.get("run")
    on_signal = trigger_data.get("on_signal")
    if not isinstance(after, str) or not after.strip():
        raise PropagateError(f"{location}.after must be a non-empty string.")
    if after not in execution_names:
        raise PropagateError(f"{location}.after references unknown execution '{after}'.")
    if not isinstance(run, str) or not run.strip():
        raise PropagateError(f"{location}.run must be a non-empty string.")
    if run not in execution_names:
        raise PropagateError(f"{location}.run references unknown execution '{run}'.")
    if on_signal is not None:
        if not isinstance(on_signal, str) or not on_signal.strip():
            raise PropagateError(f"{location}.on_signal must be a non-empty string when provided.")
        if on_signal not in signal_configs:
            raise PropagateError(f"{location}.on_signal references unknown signal '{on_signal}'.")
    when = trigger_data.get("when")
    if when is not None:
        if not isinstance(when, dict):
            raise PropagateError(f"{location}.when must be a mapping when provided.")
        if on_signal is None:
            raise PropagateError(f"{location}.when requires on_signal to be set.")
        if not when:
            LOGGER.debug("%s has an empty 'when' clause — it matches any payload, same as omitting 'when'.", location)
        else:
            _validate_trigger_when_keys(when, signal_configs[on_signal], location)
    return PropagationTriggerConfig(after=after, run=run, on_signal=on_signal, when=when)


def validate_execution_graph_is_acyclic(
    executions: dict[str, ExecutionConfig],
    propagation_triggers: list[PropagationTriggerConfig],
) -> None:
    adjacency = build_execution_graph_adjacency(executions, propagation_triggers)
    visit_state = {name: "unvisited" for name in executions}
    for execution_name in executions:
        if visit_state[execution_name] == "unvisited":
            visit_execution_graph(execution_name, adjacency, visit_state, [])


def build_execution_graph_adjacency(
    executions: dict[str, ExecutionConfig],
    propagation_triggers: list[PropagationTriggerConfig],
) -> dict[str, tuple[str, ...]]:
    adjacency = {name: [] for name in executions}
    for execution in executions.values():
        for dependency_name in execution.depends_on:
            adjacency[dependency_name].append(execution.name)
    for trigger in propagation_triggers:
        adjacency[trigger.after].append(trigger.run)
    return {name: tuple(neighbors) for name, neighbors in adjacency.items()}


def build_execution_graph(config: Config) -> ExecutionGraph:
    return ExecutionGraph(execution_order=tuple(config.executions), triggers_by_after=index_propagation_triggers(config))


def index_propagation_triggers(config: Config) -> dict[str, tuple[PropagationTriggerConfig, ...]]:
    triggers_by_after = {name: [] for name in config.executions}
    for trigger in config.propagation_triggers:
        triggers_by_after[trigger.after].append(trigger)
    return {name: tuple(triggers) for name, triggers in triggers_by_after.items()}


def visit_execution_graph(
    execution_name: str,
    adjacency: dict[str, tuple[str, ...]],
    visit_state: dict[str, str],
    stack: list[str],
) -> None:
    visit_state[execution_name] = "visiting"
    stack.append(execution_name)
    for next_execution_name in adjacency[execution_name]:
        next_state = visit_state[next_execution_name]
        if next_state == "done":
            continue
        if next_state == "visiting":
            cycle_start = stack.index(next_execution_name)
            cycle_path = stack[cycle_start:] + [next_execution_name]
            raise PropagateError(f"Execution graph contains a cycle: {' -> '.join(cycle_path)}.")
        visit_execution_graph(next_execution_name, adjacency, visit_state, stack)
    stack.pop()
    visit_state[execution_name] = "done"


def _validate_trigger_when_keys(when: dict, signal_config: SignalConfig, location: str) -> None:
    unknown_keys = sorted(set(when) - set(signal_config.payload))
    if unknown_keys:
        raise PropagateError(
            f"{location}.when references unknown payload field '{unknown_keys[0]}'."
            f" Signal '{signal_config.name}' declares: {', '.join(sorted(signal_config.payload))}."
        )
