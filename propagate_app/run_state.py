from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from .constants import LOGGER
from .errors import PropagateError
from .models import ActiveSignal, ExecutionScheduleState, RunState


def state_file_path(config_path: Path) -> Path:
    resolved = config_path.resolve()
    return resolved.parent / f".propagate-state-{resolved.stem}.yaml"


def save_run_state(state: RunState) -> None:
    data: dict[str, object] = {
        "config_path": str(state.config_path),
        "initial_execution": state.initial_execution,
        "active_names": sorted(state.schedule.active_names),
        "completed_names": sorted(state.schedule.completed_names),
        "completed_tasks": {name: dict(phases) for name, phases in state.schedule.completed_tasks.items()},
        "completed_execution_phases": dict(state.schedule.completed_execution_phases),
        "cloned_repos": {name: str(path) for name, path in state.cloned_repos.items()},
        "initialized_signal_context_dirs": sorted(str(p) for p in state.initialized_signal_context_dirs),
        "received_signal_types": sorted(state.received_signal_types),
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


def load_run_state(config_path: Path) -> RunState:
    file_path = state_file_path(config_path.resolve())
    if not file_path.exists():
        raise PropagateError(f"No run state file found at '{file_path}'. Nothing to resume.")
    try:
        with file_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        raise PropagateError(f"Failed to read run state file '{file_path}': {error}") from error
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
    completed_tasks: dict[str, dict[str, str]] = {
        name: dict(phases) for name, phases in (data.get("completed_tasks") or {}).items()
    }
    return RunState(
        config_path=Path(data["config_path"]),
        initial_execution=data["initial_execution"],
        schedule=ExecutionScheduleState(
            active_names=set(data.get("active_names") or []),
            completed_names=set(data.get("completed_names") or []),
            completed_tasks=completed_tasks,
            completed_execution_phases=dict(data.get("completed_execution_phases") or {}),
        ),
        active_signal=active_signal,
        cloned_repos=cloned_repos,
        initialized_signal_context_dirs=set(
            Path(p) for p in (data.get("initialized_signal_context_dirs") or [])
        ),
        received_signal_types=set(data.get("received_signal_types") or []),
    )


def clear_run_state(config_path: Path) -> None:
    file_path = state_file_path(config_path)
    if file_path.exists():
        file_path.unlink()
        LOGGER.debug("Cleared run state file '%s'.", file_path)
