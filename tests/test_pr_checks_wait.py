from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from propagate_app.config_executions import parse_hook_actions, parse_sub_task, parse_when_condition
from propagate_app.context_store import ensure_context_dir, resolve_execution_context_dir, write_context_value
from propagate_app.errors import PropagateError
from propagate_app.git_publish import poll_pr_action_checks
from propagate_app.git_runtime import git_do_pr_checks_wait
from propagate_app.sub_tasks import evaluate_when_condition

# ---------------------------------------------------------------------------
# Parse-time validation tests
# ---------------------------------------------------------------------------


def test_pr_checks_wait_valid_command() -> None:
    actions = parse_hook_actions(
        ["git:pr-checks-wait :result-key :status-key"], "Test", "before", set(),
    )
    assert actions == ["git:pr-checks-wait :result-key :status-key"]


def test_pr_checks_wait_with_interval_and_timeout() -> None:
    actions = parse_hook_actions(
        ["git:pr-checks-wait :result-key :status-key 15 900"], "Test", "before", set(),
    )
    assert actions == ["git:pr-checks-wait :result-key :status-key 15 900"]


def test_pr_checks_wait_with_interval_only() -> None:
    actions = parse_hook_actions(
        ["git:pr-checks-wait :result-key :status-key 5"], "Test", "before", set(),
    )
    assert actions == ["git:pr-checks-wait :result-key :status-key 5"]


def test_pr_checks_wait_missing_keys_raises() -> None:
    with pytest.raises(PropagateError, match="requires two ':'-prefixed context key arguments"):
        parse_hook_actions(["git:pr-checks-wait"], "Test", "before", set())


def test_pr_checks_wait_single_key_raises() -> None:
    with pytest.raises(PropagateError, match="requires two ':'-prefixed context key arguments"):
        parse_hook_actions(["git:pr-checks-wait :result-key"], "Test", "before", set())


def test_pr_checks_wait_non_key_arg_raises() -> None:
    with pytest.raises(PropagateError, match="requires two ':'-prefixed context key arguments"):
        parse_hook_actions(["git:pr-checks-wait plain-arg :status"], "Test", "before", set())


def test_pr_checks_wait_second_arg_not_key_raises() -> None:
    with pytest.raises(PropagateError, match="requires two ':'-prefixed context key arguments"):
        parse_hook_actions(["git:pr-checks-wait :result plain-arg"], "Test", "before", set())


def test_pr_checks_wait_invalid_interval_raises() -> None:
    with pytest.raises(PropagateError, match="must be positive integers"):
        parse_hook_actions(["git:pr-checks-wait :key :status abc"], "Test", "before", set())


def test_pr_checks_wait_zero_interval_raises() -> None:
    with pytest.raises(PropagateError, match="must be positive integers"):
        parse_hook_actions(["git:pr-checks-wait :key :status 0"], "Test", "before", set())


def test_pr_checks_wait_negative_timeout_raises() -> None:
    with pytest.raises(PropagateError, match="must be positive integers"):
        parse_hook_actions(["git:pr-checks-wait :key :status 10 -5"], "Test", "before", set())


def test_pr_checks_wait_too_many_args_raises() -> None:
    with pytest.raises(PropagateError, match="at most 4 arguments"):
        parse_hook_actions(["git:pr-checks-wait :key :status 10 1800 extra"], "Test", "before", set())


# ---------------------------------------------------------------------------
# parse_when_condition tests
# ---------------------------------------------------------------------------


def test_parse_when_valid_key() -> None:
    assert parse_when_condition(":checks-passed", "Test") == ":checks-passed"


def test_parse_when_negated_key() -> None:
    assert parse_when_condition("!:checks-passed", "Test") == "!:checks-passed"


def test_parse_when_none() -> None:
    assert parse_when_condition(None, "Test") is None


def test_parse_when_empty_raises() -> None:
    with pytest.raises(PropagateError, match="must be a non-empty string"):
        parse_when_condition("", "Test")


def test_parse_when_no_colon_raises() -> None:
    with pytest.raises(PropagateError, match="must be a ':key' or '!:key'"):
        parse_when_condition("plain-value", "Test")


def test_parse_when_just_bang_raises() -> None:
    with pytest.raises(PropagateError, match="must be a ':key' or '!:key'"):
        parse_when_condition("!plain", "Test")


# ---------------------------------------------------------------------------
# SubTaskConfig with when field
# ---------------------------------------------------------------------------


def test_sub_task_with_when_field() -> None:
    sub_task = parse_sub_task("exec", 1, {"id": "t1", "when": ":checks-ok"}, Path("/tmp"), set())
    assert sub_task.when == ":checks-ok"


def test_sub_task_with_negated_when() -> None:
    sub_task = parse_sub_task("exec", 1, {"id": "t1", "when": "!:checks-ok"}, Path("/tmp"), set())
    assert sub_task.when == "!:checks-ok"


def test_sub_task_without_when() -> None:
    sub_task = parse_sub_task("exec", 1, {"id": "t1"}, Path("/tmp"), set())
    assert sub_task.when is None


# ---------------------------------------------------------------------------
# evaluate_when_condition tests
# ---------------------------------------------------------------------------


def _make_runtime_context(tmp_path: Path):
    from propagate_app.models import GitRunState, RuntimeContext
    context_root = tmp_path / ".propagate-context"
    context_root.mkdir()
    return RuntimeContext(
        agent_command="echo",
        context_sources={},
        active_signal=None,
        initialized_signal_context_dirs=set(),
        working_dir=tmp_path / "repo",
        context_root=context_root,
        execution_name="test-exec",
        task_id="task-1",
        git_state=GitRunState(),
    )


def test_when_truthy_key_exists_non_empty(tmp_path: Path) -> None:
    rc = _make_runtime_context(tmp_path)
    context_dir = resolve_execution_context_dir(rc)
    ensure_context_dir(context_dir)
    write_context_value(context_dir, "checks-passed", "true")

    assert evaluate_when_condition(":checks-passed", rc) is True


def test_when_falsy_key_missing(tmp_path: Path) -> None:
    rc = _make_runtime_context(tmp_path)
    assert evaluate_when_condition(":checks-passed", rc) is False


def test_when_falsy_key_empty(tmp_path: Path) -> None:
    rc = _make_runtime_context(tmp_path)
    context_dir = resolve_execution_context_dir(rc)
    ensure_context_dir(context_dir)
    write_context_value(context_dir, "checks-passed", "")

    assert evaluate_when_condition(":checks-passed", rc) is False


def test_when_negated_truthy_key(tmp_path: Path) -> None:
    rc = _make_runtime_context(tmp_path)
    context_dir = resolve_execution_context_dir(rc)
    ensure_context_dir(context_dir)
    write_context_value(context_dir, "checks-passed", "true")

    assert evaluate_when_condition("!:checks-passed", rc) is False


def test_when_negated_missing_key(tmp_path: Path) -> None:
    rc = _make_runtime_context(tmp_path)
    assert evaluate_when_condition("!:checks-passed", rc) is True


def test_when_negated_empty_key(tmp_path: Path) -> None:
    rc = _make_runtime_context(tmp_path)
    context_dir = resolve_execution_context_dir(rc)
    ensure_context_dir(context_dir)
    write_context_value(context_dir, "checks-passed", "")

    assert evaluate_when_condition("!:checks-passed", rc) is True


# ---------------------------------------------------------------------------
# poll_pr_action_checks unit tests
# ---------------------------------------------------------------------------


def _make_check(name: str, status: str, conclusion: str, workflow_name: str = "CI") -> dict:
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "workflow": {"name": workflow_name},
        "detailsUrl": f"https://example.com/{name}",
    }


def _make_non_action_check(name: str) -> dict:
    return {
        "name": name,
        "status": "COMPLETED",
        "conclusion": "SUCCESS",
        "workflow": {},
        "detailsUrl": f"https://example.com/{name}",
    }


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_all_passing(mock_run: MagicMock, mock_sleep: MagicMock) -> None:
    checks = [
        _make_check("build", "COMPLETED", "SUCCESS"),
        _make_check("test", "COMPLETED", "SUCCESS"),
        _make_non_action_check("codecov"),  # should be filtered out
    ]
    mock_run.return_value = SimpleNamespace(stdout=json.dumps(checks))

    result_json, all_passed = poll_pr_action_checks(Path("/fake"), interval=10, timeout=60)
    result = json.loads(result_json)

    assert len(result) == 2
    assert all_passed
    mock_sleep.assert_not_called()


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_with_failure(mock_run: MagicMock, mock_sleep: MagicMock) -> None:
    checks = [
        _make_check("build", "COMPLETED", "SUCCESS"),
        _make_check("test", "COMPLETED", "FAILURE"),
    ]
    mock_run.return_value = SimpleNamespace(stdout=json.dumps(checks))

    result_json, all_passed = poll_pr_action_checks(Path("/fake"), interval=10, timeout=60)
    result = json.loads(result_json)

    assert len(result) == 2
    assert not all_passed


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.time.monotonic")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_waits_for_completion(mock_run: MagicMock, mock_mono: MagicMock, mock_sleep: MagicMock) -> None:
    pending = [_make_check("build", "IN_PROGRESS", "")]
    completed = [_make_check("build", "COMPLETED", "SUCCESS")]
    mock_run.side_effect = [
        SimpleNamespace(stdout=json.dumps(pending)),
        SimpleNamespace(stdout=json.dumps(completed)),
    ]
    # First call: start time, second: check deadline (not expired), third: check deadline (not expired)
    mock_mono.side_effect = [0, 5, 10]

    result_json, all_passed = poll_pr_action_checks(Path("/fake"), interval=5, timeout=60)
    assert all_passed
    mock_sleep.assert_called_once_with(5)


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.time.monotonic")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_waits_for_checks_to_appear(mock_run: MagicMock, mock_mono: MagicMock, mock_sleep: MagicMock) -> None:
    empty = [_make_non_action_check("codecov")]  # no actions checks yet
    with_actions = [
        _make_non_action_check("codecov"),
        _make_check("build", "COMPLETED", "SUCCESS"),
    ]
    mock_run.side_effect = [
        SimpleNamespace(stdout=json.dumps(empty)),
        SimpleNamespace(stdout=json.dumps(with_actions)),
    ]
    mock_mono.side_effect = [0, 5, 10]

    result_json, all_passed = poll_pr_action_checks(Path("/fake"), interval=5, timeout=60)
    result = json.loads(result_json)
    assert len(result) == 1
    assert result[0]["name"] == "build"
    assert all_passed


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.time.monotonic")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_timeout_raises(mock_run: MagicMock, mock_mono: MagicMock, mock_sleep: MagicMock) -> None:
    pending = [_make_check("build", "IN_PROGRESS", "")]
    mock_run.return_value = SimpleNamespace(stdout=json.dumps(pending))
    # Start at 0, then immediately past deadline
    mock_mono.side_effect = [0, 100]

    with pytest.raises(PropagateError, match="Timed out after 60s"):
        poll_pr_action_checks(Path("/fake"), interval=5, timeout=60)


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_cancelled_is_failure(mock_run: MagicMock, mock_sleep: MagicMock) -> None:
    checks = [_make_check("deploy", "COMPLETED", "CANCELLED")]
    mock_run.return_value = SimpleNamespace(stdout=json.dumps(checks))

    _, all_passed = poll_pr_action_checks(Path("/fake"), interval=10, timeout=60)
    assert not all_passed


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_timed_out_conclusion_is_failure(mock_run: MagicMock, mock_sleep: MagicMock) -> None:
    checks = [_make_check("slow-test", "COMPLETED", "TIMED_OUT")]
    mock_run.return_value = SimpleNamespace(stdout=json.dumps(checks))

    _, all_passed = poll_pr_action_checks(Path("/fake"), interval=10, timeout=60)
    assert not all_passed


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_action_required_is_failure(mock_run: MagicMock, mock_sleep: MagicMock) -> None:
    checks = [_make_check("review", "COMPLETED", "ACTION_REQUIRED")]
    mock_run.return_value = SimpleNamespace(stdout=json.dumps(checks))

    _, all_passed = poll_pr_action_checks(Path("/fake"), interval=10, timeout=60)
    assert not all_passed


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_stale_is_failure(mock_run: MagicMock, mock_sleep: MagicMock) -> None:
    checks = [_make_check("old-check", "COMPLETED", "STALE")]
    mock_run.return_value = SimpleNamespace(stdout=json.dumps(checks))

    _, all_passed = poll_pr_action_checks(Path("/fake"), interval=10, timeout=60)
    assert not all_passed


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_neutral_is_pass(mock_run: MagicMock, mock_sleep: MagicMock) -> None:
    checks = [_make_check("lint", "COMPLETED", "NEUTRAL")]
    mock_run.return_value = SimpleNamespace(stdout=json.dumps(checks))

    _, all_passed = poll_pr_action_checks(Path("/fake"), interval=10, timeout=60)
    assert all_passed


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_skipped_is_pass(mock_run: MagicMock, mock_sleep: MagicMock) -> None:
    checks = [_make_check("optional", "COMPLETED", "SKIPPED")]
    mock_run.return_value = SimpleNamespace(stdout=json.dumps(checks))

    _, all_passed = poll_pr_action_checks(Path("/fake"), interval=10, timeout=60)
    assert all_passed


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.run_process_command")
def test_poll_malformed_json_raises(mock_run: MagicMock, mock_sleep: MagicMock) -> None:
    mock_run.return_value = SimpleNamespace(stdout="not valid json")

    with pytest.raises(PropagateError, match="Failed to parse PR checks output as JSON"):
        poll_pr_action_checks(Path("/fake"), interval=10, timeout=60)


# ---------------------------------------------------------------------------
# git_do_pr_checks_wait integration tests
# ---------------------------------------------------------------------------


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.run_process_command")
def test_do_pr_checks_wait_stores_and_succeeds(mock_run: MagicMock, mock_sleep: MagicMock, tmp_path: Path) -> None:
    checks = [_make_check("build", "COMPLETED", "SUCCESS")]
    mock_run.return_value = SimpleNamespace(stdout=json.dumps(checks))
    runtime_context = _make_runtime_context(tmp_path)

    git_do_pr_checks_wait("test-exec", ":check-results", ":checks-passed", 10, 60, runtime_context)

    context_dir = resolve_execution_context_dir(runtime_context)
    stored = (context_dir / "check-results").read_text(encoding="utf-8")
    result = json.loads(stored)
    assert len(result) == 1
    assert result[0]["name"] == "build"
    status = (context_dir / "checks-passed").read_text(encoding="utf-8")
    assert status == "true"


@patch("propagate_app.git_publish.time.sleep")
@patch("propagate_app.git_publish.run_process_command")
def test_do_pr_checks_wait_failure_no_raise(mock_run: MagicMock, mock_sleep: MagicMock, tmp_path: Path) -> None:
    checks = [
        _make_check("build", "COMPLETED", "SUCCESS"),
        _make_check("test", "COMPLETED", "FAILURE"),
    ]
    mock_run.return_value = SimpleNamespace(stdout=json.dumps(checks))
    runtime_context = _make_runtime_context(tmp_path)

    # Should NOT raise
    git_do_pr_checks_wait("test-exec", ":check-results", ":checks-passed", 10, 60, runtime_context)

    context_dir = resolve_execution_context_dir(runtime_context)
    stored = (context_dir / "check-results").read_text(encoding="utf-8")
    result = json.loads(stored)
    assert len(result) == 2
    status = (context_dir / "checks-passed").read_text(encoding="utf-8")
    assert status == ""


# ---------------------------------------------------------------------------
# Subtask when-based skipping integration test
# ---------------------------------------------------------------------------


def test_subtask_skipped_when_condition_falsy(tmp_path: Path) -> None:
    from propagate_app.models import ExecutionConfig, SubTaskConfig

    rc = _make_runtime_context(tmp_path)
    sub_tasks = [
        SubTaskConfig(task_id="always", prompt_path=None, before=[], after=[], on_failure=[]),
        SubTaskConfig(task_id="only-on-pass", prompt_path=None, before=[], after=[], on_failure=[], when=":checks-passed"),
        SubTaskConfig(task_id="only-on-fail", prompt_path=None, before=[], after=[], on_failure=[], when="!:checks-passed"),
    ]
    execution = ExecutionConfig(
        name="test-exec", repository="repo", depends_on=[], signals=[],
        sub_tasks=sub_tasks, git=None,
    )

    completed_tasks: list[str] = []

    def track_phase(exec_name: str, task_id: str, phase: str) -> None:
        if phase == "after":
            completed_tasks.append(task_id)

    from propagate_app.sub_tasks import run_execution_sub_tasks
    run_execution_sub_tasks(execution, rc, on_phase_completed=track_phase)

    # :checks-passed doesn't exist → falsy
    # "always" runs, "only-on-pass" skipped, "only-on-fail" runs
    assert "always" in completed_tasks
    assert "only-on-pass" not in completed_tasks
    assert "only-on-fail" in completed_tasks


def test_subtask_runs_when_condition_truthy(tmp_path: Path) -> None:
    from propagate_app.models import ExecutionConfig, SubTaskConfig
    from propagate_app.sub_tasks import run_execution_sub_tasks

    rc = _make_runtime_context(tmp_path)
    context_dir = resolve_execution_context_dir(rc)
    ensure_context_dir(context_dir)
    write_context_value(context_dir, "checks-passed", "true")

    sub_tasks = [
        SubTaskConfig(task_id="only-on-pass", prompt_path=None, before=[], after=[], on_failure=[], when=":checks-passed"),
        SubTaskConfig(task_id="only-on-fail", prompt_path=None, before=[], after=[], on_failure=[], when="!:checks-passed"),
    ]
    execution = ExecutionConfig(
        name="test-exec", repository="repo", depends_on=[], signals=[],
        sub_tasks=sub_tasks, git=None,
    )

    completed_tasks: list[str] = []

    def track_phase(exec_name: str, task_id: str, phase: str) -> None:
        if phase == "after":
            completed_tasks.append(task_id)

    run_execution_sub_tasks(execution, rc, on_phase_completed=track_phase)

    assert "only-on-pass" in completed_tasks
    assert "only-on-fail" not in completed_tasks
