from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from propagate_app.config_executions import parse_sub_task
from propagate_app.context_store import ensure_context_dir, write_context_value
from propagate_app.errors import PropagateError
from propagate_app.models import ExecutionConfig, RuntimeContext, SubTaskConfig
from propagate_app.sub_tasks import run_execution_sub_tasks


def _make_sub_task(
    task_id: str, *, goto: str | None = None, when: str | None = None, max_goto: int = 3, on_max_goto: str = "fail",
) -> SubTaskConfig:
    return SubTaskConfig(
        task_id=task_id,
        prompt_path=Path("/fake/prompt.md"),
        before=[],
        after=[],
        on_failure=[],
        when=when,
        goto=goto,
        max_goto=max_goto,
        on_max_goto=on_max_goto,
    )


def _make_runtime_context(tmp_path: Path) -> RuntimeContext:
    context_root = tmp_path / "context"
    ensure_context_dir(context_root)
    return RuntimeContext(
        agents={"default": "echo test"},
        default_agent="default",
        context_sources={},
        active_signal=None,
        initialized_signal_context_dirs=set(),
        working_dir=tmp_path,
        context_root=context_root,
        execution_name="test-exec",
        task_id="",
    )


def test_parse_sub_task_accepts_max_goto(tmp_path):
    seen_ids = {"implement"}
    result = parse_sub_task(
        "ex", 2,
        {"id": "reroute", "when": "!:done", "goto": "implement", "max_goto": 5},
        tmp_path, set(), None, seen_ids,
    )
    assert result.goto == "implement"
    assert result.max_goto == 5


def test_parse_sub_task_default_max_goto(tmp_path):
    seen_ids = {"implement"}
    result = parse_sub_task(
        "ex", 2,
        {"id": "reroute", "when": "!:done", "goto": "implement"},
        tmp_path, set(), None, seen_ids,
    )
    assert result.max_goto == 3


def test_parse_sub_task_max_goto_without_goto_raises(tmp_path):
    with pytest.raises(PropagateError, match="'max_goto' requires 'goto'"):
        parse_sub_task(
            "ex", 1,
            {"id": "step", "prompt": None, "max_goto": 5},
            tmp_path, set(), None, set(),
        )


def test_parse_sub_task_max_goto_must_be_positive_int(tmp_path):
    seen_ids = {"implement"}
    with pytest.raises(PropagateError, match="must be a positive integer"):
        parse_sub_task(
            "ex", 2,
            {"id": "reroute", "when": "!:done", "goto": "implement", "max_goto": 0},
            tmp_path, set(), None, seen_ids,
        )


def test_parse_sub_task_max_goto_rejects_non_int(tmp_path):
    seen_ids = {"implement"}
    with pytest.raises(PropagateError, match="must be a positive integer"):
        parse_sub_task(
            "ex", 2,
            {"id": "reroute", "when": "!:done", "goto": "implement", "max_goto": "three"},
            tmp_path, set(), None, seen_ids,
        )


def test_parse_sub_task_goto_without_when_raises(tmp_path):
    seen_ids = {"implement"}
    with pytest.raises(PropagateError, match="'goto' requires 'when'"):
        parse_sub_task(
            "ex", 2,
            {"id": "reroute", "goto": "implement"},
            tmp_path, set(), None, seen_ids,
        )


def test_goto_exceeds_max_raises(tmp_path):
    """Direct goto that fires more than max_goto times raises PropagateError."""
    rc = _make_runtime_context(tmp_path)
    exec_ctx_dir = rc.context_root / "test-exec"
    ensure_context_dir(exec_ctx_dir)

    sub_tasks = [
        _make_sub_task("implement"),
        _make_sub_task("reroute", goto="implement", when="!:done", max_goto=2),
    ]
    execution = ExecutionConfig(
        name="test-exec", repository="repo", depends_on=[], signals=[],
        sub_tasks=sub_tasks, git=None, before=[], after=[],
    )

    call_count = 0

    def tracking_run(exec_name, sub_task, runtime_context, git_config=None, completed_phase=None, on_phase_completed=None):
        nonlocal call_count
        call_count += 1
        # Never set :done, so reroute always fires

    with patch("propagate_app.sub_tasks.run_sub_task", side_effect=tracking_run):
        with pytest.raises(PropagateError, match="exceeded maximum goto count"):
            run_execution_sub_tasks(execution, rc)

    # implement ran 3 times (initial + 2 gotos), reroute ran 2 times (3rd blocked before running)
    assert call_count == 5


def test_goto_within_limit_succeeds(tmp_path):
    """Direct goto that fires within max_goto times completes normally."""
    rc = _make_runtime_context(tmp_path)
    exec_ctx_dir = rc.context_root / "test-exec"
    ensure_context_dir(exec_ctx_dir)

    sub_tasks = [
        _make_sub_task("implement"),
        _make_sub_task("reroute", goto="implement", when="!:done", max_goto=3),
        _make_sub_task("final"),
    ]
    execution = ExecutionConfig(
        name="test-exec", repository="repo", depends_on=[], signals=[],
        sub_tasks=sub_tasks, git=None, before=[], after=[],
    )

    ran_tasks: list[str] = []
    reroute_count = 0

    def tracking_run(exec_name, sub_task, runtime_context, git_config=None, completed_phase=None, on_phase_completed=None):
        nonlocal reroute_count
        ran_tasks.append(sub_task.task_id)
        if sub_task.task_id == "reroute":
            reroute_count += 1
            # On the 2nd reroute invocation, set :done so the when condition stops it next time
            if reroute_count >= 2:
                write_context_value(exec_ctx_dir, ":done", "true")

    with patch("propagate_app.sub_tasks.run_sub_task", side_effect=tracking_run):
        run_execution_sub_tasks(execution, rc)

    # implement, reroute(goto), implement, reroute(sets done, goto), implement, reroute skipped, final
    assert ran_tasks == ["implement", "reroute", "implement", "reroute", "implement", "final"]


def test_on_max_goto_fail_is_default():
    sub_task = _make_sub_task("x", goto="y", when="!:done")
    assert sub_task.on_max_goto == "fail"


def test_parse_on_max_goto_continue(tmp_path):
    seen_ids = {"implement"}
    result = parse_sub_task(
        "ex", 2,
        {"id": "reroute", "when": "!:done", "goto": "implement", "on_max_goto": "continue"},
        tmp_path, set(), None, seen_ids,
    )
    assert result.on_max_goto == "continue"


def test_parse_on_max_goto_without_goto_raises(tmp_path):
    with pytest.raises(PropagateError, match="'on_max_goto' requires 'goto'"):
        parse_sub_task(
            "ex", 1,
            {"id": "step", "when": ":flag", "on_max_goto": "continue"},
            tmp_path, set(), None, set(),
        )


def test_parse_on_max_goto_invalid_value_raises(tmp_path):
    seen_ids = {"implement"}
    with pytest.raises(PropagateError, match="'on_max_goto' must be 'fail' or 'continue'"):
        parse_sub_task(
            "ex", 2,
            {"id": "reroute", "when": "!:done", "goto": "implement", "on_max_goto": "skip"},
            tmp_path, set(), None, seen_ids,
        )


def test_on_max_goto_continue_skips_goto(tmp_path):
    """When max_goto is exceeded with on_max_goto=continue, execution proceeds to next task."""
    rc = _make_runtime_context(tmp_path)
    exec_ctx_dir = rc.context_root / "test-exec"
    ensure_context_dir(exec_ctx_dir)

    sub_tasks = [
        _make_sub_task("implement"),
        _make_sub_task("reroute", goto="implement", when="!:done", max_goto=2, on_max_goto="continue"),
        _make_sub_task("final"),
    ]
    execution = ExecutionConfig(
        name="test-exec", repository="repo", depends_on=[], signals=[],
        sub_tasks=sub_tasks, git=None, before=[], after=[],
    )

    ran_tasks: list[str] = []

    def tracking_run(exec_name, sub_task, runtime_context, git_config=None, completed_phase=None, on_phase_completed=None):
        ran_tasks.append(sub_task.task_id)
        # Never set :done, so reroute always wants to fire

    with patch("propagate_app.sub_tasks.run_sub_task", side_effect=tracking_run):
        run_execution_sub_tasks(execution, rc)

    # implement, reroute(goto#1), implement, reroute(goto#2), implement, reroute(skipped, max exceeded), final
    assert ran_tasks == ["implement", "reroute", "implement", "reroute", "implement", "final"]
