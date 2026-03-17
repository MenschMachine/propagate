from __future__ import annotations

from pathlib import Path

import pytest

from propagate_app.errors import PropagateError
from propagate_app.models import (
    AgentConfig,
    Config,
    ExecutionConfig,
    ExecutionScheduleState,
    RunState,
    SubTaskConfig,
)
from propagate_app.run_state import (
    apply_forced_resume_if_targeted,
    parse_resume_target,
    rewrite_state_for_forced_resume,
    save_run_state,
)


def _make_config(executions: dict[str, ExecutionConfig]) -> Config:
    return Config(
        version="6",
        agent=AgentConfig(command="echo"),
        repositories={"repo": _repo()},
        context_sources={},
        signals={},
        propagation_triggers=[],
        executions=executions,
        config_path=Path("/tmp/test-config.yaml"),
    )


def _repo():
    from propagate_app.models import RepositoryConfig
    return RepositoryConfig(name="repo", path=Path("/tmp/repo"))


def _execution(name: str, depends_on: list[str] | None = None, tasks: list[str] | None = None) -> ExecutionConfig:
    sub_tasks = [
        SubTaskConfig(
            task_id=tid,
            prompt_path=None,
            before=[],
            after=[],
            on_failure=[],
        )
        for tid in (tasks or [])
    ]
    return ExecutionConfig(
        name=name,
        repository="repo",
        depends_on=depends_on or [],
        signals=[],
        sub_tasks=sub_tasks,
        git=None,
    )


def _run_state(config: Config) -> RunState:
    first_exec = next(iter(config.executions))
    return RunState(
        config_path=config.config_path,
        initial_execution=first_exec,
        schedule=ExecutionScheduleState(active_names=set(), completed_names=set()),
        active_signal=None,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
    )


# --- parse_resume_target ---

def test_parse_resume_target_with_task():
    assert parse_resume_target("suggest/wait-for-verdict") == ("suggest", "wait-for-verdict")


def test_parse_resume_target_execution_only():
    assert parse_resume_target("suggest") == ("suggest", None)


# --- rewrite_state_for_forced_resume ---

def test_rewrite_marks_predecessors_completed(tmp_path):
    """Linear DAG A -> B -> C, target B. A should be completed, B active but not completed."""
    config = _make_config({
        "A": _execution("A"),
        "B": _execution("B", depends_on=["A"]),
        "C": _execution("C", depends_on=["B"]),
    })
    config = config.__class__(**{**config.__dict__, "config_path": tmp_path / "cfg.yaml"})
    (tmp_path / "cfg.yaml").touch()
    state = _run_state(config)

    rewrite_state_for_forced_resume(state, config, "B", None)

    assert "A" in state.schedule.active_names
    assert "B" in state.schedule.active_names
    assert "C" not in state.schedule.active_names
    assert "A" in state.schedule.completed_names
    assert "B" not in state.schedule.completed_names


def test_rewrite_marks_tasks_before_target(tmp_path):
    """Target suggest/publish. Tasks before publish marked PHASE_AFTER, publish absent."""
    config = _make_config({
        "suggest": _execution("suggest", tasks=["analyze", "draft", "publish"]),
    })
    config = config.__class__(**{**config.__dict__, "config_path": tmp_path / "cfg.yaml"})
    (tmp_path / "cfg.yaml").touch()
    state = _run_state(config)

    rewrite_state_for_forced_resume(state, config, "suggest", "publish")

    completed_tasks = state.schedule.completed_tasks.get("suggest", {})
    assert completed_tasks.get("analyze") == "after"
    assert completed_tasks.get("draft") == "after"
    assert "publish" not in completed_tasks


def test_rewrite_execution_only_starts_fresh(tmp_path):
    """Target suggest (no task). No completed tasks for suggest, no execution phase."""
    config = _make_config({
        "suggest": _execution("suggest", tasks=["analyze", "draft"]),
    })
    config = config.__class__(**{**config.__dict__, "config_path": tmp_path / "cfg.yaml"})
    (tmp_path / "cfg.yaml").touch()
    state = _run_state(config)

    rewrite_state_for_forced_resume(state, config, "suggest", None)

    assert state.schedule.completed_tasks.get("suggest", {}) == {}
    assert "suggest" not in state.schedule.completed_execution_phases


def test_rewrite_sets_execution_before_phase(tmp_path):
    """Target suggest/wait-for-verdict. Execution phase should be 'before'."""
    config = _make_config({
        "suggest": _execution("suggest", tasks=["analyze", "wait-for-verdict", "publish"]),
    })
    config = config.__class__(**{**config.__dict__, "config_path": tmp_path / "cfg.yaml"})
    (tmp_path / "cfg.yaml").touch()
    state = _run_state(config)

    rewrite_state_for_forced_resume(state, config, "suggest", "wait-for-verdict")

    assert state.schedule.completed_execution_phases["suggest"] == "before"


def test_rewrite_invalid_execution_raises(tmp_path):
    config = _make_config({
        "suggest": _execution("suggest"),
    })
    config = config.__class__(**{**config.__dict__, "config_path": tmp_path / "cfg.yaml"})
    (tmp_path / "cfg.yaml").touch()
    state = _run_state(config)

    with pytest.raises(PropagateError, match="not found in config"):
        rewrite_state_for_forced_resume(state, config, "nonexistent", None)


def test_rewrite_invalid_task_raises(tmp_path):
    config = _make_config({
        "suggest": _execution("suggest", tasks=["analyze", "draft"]),
    })
    config = config.__class__(**{**config.__dict__, "config_path": tmp_path / "cfg.yaml"})
    (tmp_path / "cfg.yaml").touch()
    state = _run_state(config)

    with pytest.raises(PropagateError, match="not found in execution"):
        rewrite_state_for_forced_resume(state, config, "suggest", "nonexistent")


# --- CLI argparse ---

def test_cli_resume_nargs():
    from propagate_app.cli import build_parser

    parser = build_parser()

    # --resume without value -> True
    args = parser.parse_args(["run", "--config", "x.yaml", "--resume"])
    assert args.resume is True

    # --resume with value -> string
    args = parser.parse_args(["run", "--config", "x.yaml", "--resume", "suggest/task1"])
    assert args.resume == "suggest/task1"

    # no --resume -> False
    args = parser.parse_args(["run", "--config", "x.yaml"])
    assert args.resume is False

    # serve --resume with value
    args = parser.parse_args(["serve", "--config", "x.yaml", "--resume", "suggest"])
    assert args.resume == "suggest"

    # serve --resume without value
    args = parser.parse_args(["serve", "--config", "x.yaml", "--resume"])
    assert args.resume is True


# --- apply_forced_resume_if_targeted ---

def test_apply_forced_resume_loads_and_rewrites(tmp_path):
    """apply_forced_resume_if_targeted loads state and applies rewrite when target is given."""
    config = _make_config({
        "A": _execution("A"),
        "B": _execution("B", depends_on=["A"], tasks=["t1", "t2"]),
    })
    config = config.__class__(**{**config.__dict__, "config_path": tmp_path / "cfg.yaml"})
    (tmp_path / "cfg.yaml").touch()
    # Save initial state so load_run_state can find it
    state = _run_state(config)
    save_run_state(state)

    result = apply_forced_resume_if_targeted(tmp_path / "cfg.yaml", config, "B/t2")

    assert "A" in result.schedule.completed_names
    assert "B" not in result.schedule.completed_names
    assert result.schedule.completed_tasks["B"] == {"t1": "after"}


def test_apply_forced_resume_no_target_loads_unchanged(tmp_path):
    """apply_forced_resume_if_targeted with no target just loads state as-is."""
    config = _make_config({
        "A": _execution("A"),
    })
    config = config.__class__(**{**config.__dict__, "config_path": tmp_path / "cfg.yaml"})
    (tmp_path / "cfg.yaml").touch()
    state = _run_state(config)
    state.schedule.active_names.add("A")
    state.schedule.completed_names.add("A")
    save_run_state(state)

    result = apply_forced_resume_if_targeted(tmp_path / "cfg.yaml", config, None)

    assert result.schedule.completed_names == {"A"}
