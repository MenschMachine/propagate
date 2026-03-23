from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from .constants import LOGGER
from .errors import PropagateError
from .models import ActiveSignal, Config, ExecutionStatus, PhaseStatus, RunState, TaskStatus


def state_file_path(config_path: Path) -> Path:
    resolved = config_path.resolve()
    return resolved.parent / f".propagate-state-{resolved.stem}.yaml"


def save_run_state(state: RunState) -> None:
    executions_data: dict[str, object] = {}
    for name, es in state.executions.items():
        tasks_data: dict[str, object] = {}
        for task_id, ts in es.tasks.items():
            tasks_data[task_id] = {
                "before_completed": ts.phases.before_completed,
                "agent_completed": ts.phases.agent_completed,
                "after_completed": ts.phases.after_completed,
            }
        executions_data[name] = {
            "state": es.state,
            "before_completed": es.before_completed,
            "after_completed": es.after_completed,
            "tasks": tasks_data,
        }
    data: dict[str, object] = {
        "config_path": str(state.config_path),
        "initial_execution": state.initial_execution,
        "executions": executions_data,
        "activated_triggers": [list(t) for t in sorted(state.activated_triggers, key=lambda t: (t[0], t[1] or "", t[2]))],
        "cloned_repos": {name: str(path) for name, path in state.cloned_repos.items()},
        "initialized_signal_context_dirs": sorted(str(p) for p in state.initialized_signal_context_dirs),
        "received_signal_types": sorted(state.received_signal_types),
        "metadata": state.metadata,
    }
    if state.active_signal is not None:
        data["active_signal"] = {
            "signal_type": state.active_signal.signal_type,
            "payload": state.active_signal.payload,
            "source": state.active_signal.source,
        }
    file_path = state_file_path(state.config_path)
    fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.dump(data, handle, default_flow_style=False)
        Path(tmp_path).replace(file_path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    LOGGER.debug("Saved run state to '%s'.", file_path)


def read_cloned_repos(config_path: Path) -> dict[str, Path]:
    """Read cloned_repos from the state file without full validation."""
    file_path = state_file_path(config_path.resolve())
    if not file_path.exists():
        return {}
    try:
        with file_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError):
        LOGGER.warning("Could not read cloned repos from state file '%s'.", file_path)
        return {}
    return {name: Path(p) for name, p in (data.get("cloned_repos") or {}).items()}


def load_run_state(config_path: Path) -> RunState:
    file_path = state_file_path(config_path.resolve())
    if not file_path.exists():
        raise PropagateError(f"No run state file found at '{file_path}'. Nothing to resume.")
    try:
        with file_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        raise PropagateError(f"Failed to read run state file '{file_path}': {error}") from error
    if "active_names" in data or "completed_names" in data:
        raise PropagateError("State file is in old format; run 'propagate clear' first.")
    cloned_repos: dict[str, Path] = {}
    for name, path_str in (data.get("cloned_repos") or {}).items():
        clone_path = Path(path_str)
        if not clone_path.exists():
            raise PropagateError(
                f"Cloned repository '{name}' directory no longer exists: {clone_path}"
            )
        cloned_repos[name] = clone_path
    active_signal = None
    if "active_signal" in data:
        sig = data["active_signal"]
        active_signal = ActiveSignal(
            signal_type=sig["signal_type"],
            payload=sig.get("payload", {}),
            source=sig["source"],
        )
    executions: dict[str, ExecutionStatus] = {}
    for name, es_data in (data.get("executions") or {}).items():
        tasks: dict[str, TaskStatus] = {}
        for task_id, ts_data in (es_data.get("tasks") or {}).items():
            tasks[task_id] = TaskStatus(
                phases=PhaseStatus(
                    before_completed=ts_data.get("before_completed", False),
                    agent_completed=ts_data.get("agent_completed", False),
                    after_completed=ts_data.get("after_completed", False),
                )
            )
        executions[name] = ExecutionStatus(
            state=es_data.get("state", "inactive"),
            tasks=tasks,
            before_completed=es_data.get("before_completed", False),
            after_completed=es_data.get("after_completed", False),
        )
    activated_triggers: set[tuple[str, str | None, str]] = set()
    for trigger_list in data.get("activated_triggers") or []:
        activated_triggers.add((trigger_list[0], trigger_list[1], trigger_list[2]))
    return RunState(
        config_path=Path(data["config_path"]),
        initial_execution=data["initial_execution"],
        executions=executions,
        active_signal=active_signal,
        cloned_repos=cloned_repos,
        initialized_signal_context_dirs=set(
            Path(p) for p in (data.get("initialized_signal_context_dirs") or [])
        ),
        activated_triggers=activated_triggers,
        received_signal_types=set(data.get("received_signal_types") or []),
        metadata=data.get("metadata") or {},
    )


def parse_resume_target(target: str) -> tuple[str, str | None]:
    parts = target.split("/", 1)
    return (parts[0], parts[1] if len(parts) > 1 else None)


def rewrite_state_for_forced_resume(
    run_state: RunState,
    config: Config,
    target_execution: str,
    target_task: str | None,
) -> None:
    from .graph import build_execution_graph
    from .scheduler import activate_execution_with_dependencies, activate_matching_triggers

    if target_execution not in config.executions:
        raise PropagateError(f"Execution '{target_execution}' not found in config.")
    execution = config.executions[target_execution]
    if target_task is not None:
        task_ids = [t.task_id for t in execution.sub_tasks]
        if target_task not in task_ids:
            raise PropagateError(
                f"Task '{target_task}' not found in execution '{target_execution}'. "
                f"Available tasks: {', '.join(task_ids)}"
            )

    executions: dict[str, ExecutionStatus] = {}

    # Activate target and its depends_on deps
    activate_execution_with_dependencies(config, target_execution, executions)

    # Also activate transitive predecessors via propagation triggers
    for pred in _find_trigger_predecessors(config, target_execution):
        activate_execution_with_dependencies(config, pred, executions)

    # Mark all except target as completed
    for name, es in executions.items():
        if name != target_execution:
            es.state = "completed"
            es.before_completed = True
            es.after_completed = True

    # Target execution is in_progress
    target_es = executions[target_execution]
    target_es.state = "in_progress"

    if target_task is not None:
        target_es.before_completed = True
        for sub_task in execution.sub_tasks:
            if sub_task.task_id == target_task:
                break
            target_es.tasks[sub_task.task_id] = TaskStatus(
                phases=PhaseStatus(
                    before_completed=True,
                    agent_completed=True,
                    after_completed=True,
                )
            )

    # Replay propagation triggers for completed predecessors to activate siblings
    execution_graph = build_execution_graph(config)
    activated_triggers: set[tuple[str, str | None, str]] = set()
    for name in list(executions):
        if executions[name].state == "completed":
            activate_matching_triggers(
                config, execution_graph, name, None, executions, activated_triggers,
            )

    run_state.executions = executions
    run_state.activated_triggers = activated_triggers
    save_run_state(run_state)
    LOGGER.debug("Rewrote run state for forced resume at '%s'.", target_execution + (f"/{target_task}" if target_task else ""))


def _find_trigger_predecessors(config: Config, target_execution: str) -> set[str]:
    """Walk backward through non-signal propagation triggers to find all transitive predecessors."""
    predecessors: set[str] = set()
    visited: set[str] = set()
    queue = [target_execution]
    while queue:
        current = queue.pop()
        if current in visited:
            continue
        visited.add(current)
        for trigger in config.propagation_triggers:
            if trigger.run == current and trigger.on_signal is None and trigger.after not in visited:
                predecessors.add(trigger.after)
                queue.append(trigger.after)
    return predecessors


def apply_forced_resume_if_targeted(
    config_path: Path,
    config: Config,
    resume_target: str | None,
) -> RunState:
    """Load run state and optionally rewrite it for a forced resume target.

    Centralises the load-parse-rewrite sequence used by both ``run`` and ``serve``.
    """
    run_state = load_run_state(config_path)
    if resume_target is not None:
        target_exec, target_task = parse_resume_target(resume_target)
        LOGGER.info("Forced resume from '%s'.", resume_target)
        rewrite_state_for_forced_resume(run_state, config, target_exec, target_task)
    return run_state


def clear_run_state(config_path: Path) -> None:
    file_path = state_file_path(config_path)
    if file_path.exists():
        file_path.unlink()
        LOGGER.debug("Cleared run state file '%s'.", file_path)
