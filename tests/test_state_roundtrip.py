from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from propagate_app.errors import PropagateError
from propagate_app.models import (
    ActiveSignal,
    ExecutionStatus,
    PhaseStatus,
    RunState,
    TaskStatus,
)
from propagate_app.run_state import load_run_state, save_run_state, state_file_path


@pytest.fixture()
def workspace(tmp_path):
    return tmp_path


def _make_run_state(config_path: Path) -> RunState:
    return RunState(
        config_path=config_path,
        initial_execution="exec_a",
        executions={
            "exec_a": ExecutionStatus(
                state="completed",
                before_completed=True,
                after_completed=True,
                tasks={
                    "task1": TaskStatus(phases=PhaseStatus(before_completed=True, agent_completed=True, after_completed=True)),
                    "task2": TaskStatus(phases=PhaseStatus(before_completed=True, agent_completed=True, after_completed=True)),
                },
            ),
            "exec_b": ExecutionStatus(
                state="in_progress",
                before_completed=True,
                after_completed=False,
                tasks={
                    "task_x": TaskStatus(phases=PhaseStatus(before_completed=True, agent_completed=False, after_completed=False)),
                },
            ),
            "exec_c": ExecutionStatus(state="pending"),
            "exec_d": ExecutionStatus(state="inactive"),
        },
        activated_triggers={
            ("exec_a", None, "exec_b"),
            ("exec_a", "my_signal", "exec_c"),
        },
        active_signal=ActiveSignal(signal_type="my_signal", payload={"key": "value"}, source="external"),
        cloned_repos={},
        initialized_signal_context_dirs=set(),
        received_signal_types={"my_signal"},
        metadata={"chat_id": "123"},
    )


def test_roundtrip_preserves_all_fields(workspace):
    config_path = workspace / "test.yaml"
    config_path.write_text("version: '6'\n", encoding="utf-8")
    state = _make_run_state(config_path)
    save_run_state(state)
    loaded = load_run_state(config_path)

    assert loaded.config_path == state.config_path
    assert loaded.initial_execution == state.initial_execution
    assert loaded.metadata == state.metadata
    assert loaded.received_signal_types == state.received_signal_types
    assert loaded.activated_triggers == state.activated_triggers

    assert loaded.active_signal is not None
    assert loaded.active_signal.signal_type == "my_signal"
    assert loaded.active_signal.payload == {"key": "value"}

    assert set(loaded.executions.keys()) == {"exec_a", "exec_b", "exec_c", "exec_d"}

    ea = loaded.executions["exec_a"]
    assert ea.state == "completed"
    assert ea.before_completed is True
    assert ea.after_completed is True
    assert ea.tasks["task1"].phases.before_completed is True
    assert ea.tasks["task1"].phases.agent_completed is True
    assert ea.tasks["task1"].phases.after_completed is True
    assert ea.tasks["task2"].is_completed is True

    eb = loaded.executions["exec_b"]
    assert eb.state == "in_progress"
    assert eb.before_completed is True
    assert eb.after_completed is False
    assert eb.tasks["task_x"].phases.before_completed is True
    assert eb.tasks["task_x"].phases.agent_completed is False

    ec = loaded.executions["exec_c"]
    assert ec.state == "pending"
    assert ec.tasks == {}

    ed = loaded.executions["exec_d"]
    assert ed.state == "inactive"


def test_old_format_raises_error(workspace):
    config_path = workspace / "test.yaml"
    config_path.write_text("version: '6'\n", encoding="utf-8")
    state_path = state_file_path(config_path)
    old_data = {
        "config_path": str(config_path),
        "initial_execution": "exec_a",
        "active_names": ["exec_a"],
        "completed_names": [],
        "completed_tasks": {},
        "completed_execution_phases": {},
        "cloned_repos": {},
    }
    state_path.write_text(yaml.dump(old_data), encoding="utf-8")

    with pytest.raises(PropagateError, match="old format"):
        load_run_state(config_path)


def test_roundtrip_no_active_signal(workspace):
    config_path = workspace / "test.yaml"
    config_path.write_text("version: '6'\n", encoding="utf-8")
    state = RunState(
        config_path=config_path,
        initial_execution="a",
        executions={"a": ExecutionStatus(state="pending")},
        active_signal=None,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
    )
    save_run_state(state)
    loaded = load_run_state(config_path)
    assert loaded.active_signal is None
    assert loaded.executions["a"].state == "pending"


def test_roundtrip_empty_executions(workspace):
    config_path = workspace / "test.yaml"
    config_path.write_text("version: '6'\n", encoding="utf-8")
    state = RunState(
        config_path=config_path,
        initial_execution="a",
        executions={},
        active_signal=None,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
    )
    save_run_state(state)
    loaded = load_run_state(config_path)
    assert loaded.executions == {}
    assert loaded.activated_triggers == set()
