from __future__ import annotations

from pathlib import Path

from propagate_app.context_store import ensure_context_dir, write_context_value
from propagate_app.models import RuntimeContext
from propagate_app.sub_tasks import evaluate_when_condition


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


def test_when_positive_key_exists(tmp_path):
    rc = _make_runtime_context(tmp_path)
    exec_dir = rc.context_root / "test-exec"
    ensure_context_dir(exec_dir)
    write_context_value(exec_dir, ":checks-passed", "true")
    assert evaluate_when_condition(":checks-passed", rc) is True


def test_when_positive_key_missing(tmp_path):
    rc = _make_runtime_context(tmp_path)
    exec_dir = rc.context_root / "test-exec"
    ensure_context_dir(exec_dir)
    assert evaluate_when_condition(":checks-passed", rc) is False


def test_when_positive_key_empty(tmp_path):
    rc = _make_runtime_context(tmp_path)
    exec_dir = rc.context_root / "test-exec"
    ensure_context_dir(exec_dir)
    write_context_value(exec_dir, ":checks-passed", "")
    assert evaluate_when_condition(":checks-passed", rc) is False


def test_when_negated_key_exists(tmp_path):
    rc = _make_runtime_context(tmp_path)
    exec_dir = rc.context_root / "test-exec"
    ensure_context_dir(exec_dir)
    write_context_value(exec_dir, ":checks-passed", "true")
    assert evaluate_when_condition("!:checks-passed", rc) is False


def test_when_negated_key_missing(tmp_path):
    rc = _make_runtime_context(tmp_path)
    exec_dir = rc.context_root / "test-exec"
    ensure_context_dir(exec_dir)
    assert evaluate_when_condition("!:checks-passed", rc) is True


def test_when_negated_key_empty(tmp_path):
    rc = _make_runtime_context(tmp_path)
    exec_dir = rc.context_root / "test-exec"
    ensure_context_dir(exec_dir)
    write_context_value(exec_dir, ":checks-passed", "")
    assert evaluate_when_condition("!:checks-passed", rc) is True
