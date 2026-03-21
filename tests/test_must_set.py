"""Tests for the must_set sub-task feature."""

from pathlib import Path

import pytest

from propagate_app.config_executions import parse_must_set, parse_sub_task
from propagate_app.context_store import ensure_context_dir, write_context_value
from propagate_app.errors import PropagateError
from propagate_app.models import GitRunState, RuntimeContext, SubTaskConfig
from propagate_app.prompts import append_must_set_notice, build_sub_task_prompt
from propagate_app.sub_tasks import validate_must_set_keys

# ---------------------------------------------------------------------------
# parse_must_set
# ---------------------------------------------------------------------------


def test_parse_must_set_none():
    assert parse_must_set(None, "loc") == []


def test_parse_must_set_valid():
    result = parse_must_set([":foo", ":bar-baz"], "loc")
    assert result == [":foo", ":bar-baz"]


def test_parse_must_set_empty_list():
    with pytest.raises(PropagateError, match="non-empty list"):
        parse_must_set([], "loc")


def test_parse_must_set_invalid_key():
    with pytest.raises(PropagateError, match="Invalid context key"):
        parse_must_set(["!!!"], "loc")


def test_parse_must_set_non_string_entry():
    with pytest.raises(PropagateError, match="non-empty string"):
        parse_must_set([123], "loc")


def test_parse_must_set_empty_string_entry():
    with pytest.raises(PropagateError, match="non-empty string"):
        parse_must_set([""], "loc")


# ---------------------------------------------------------------------------
# parse_sub_task integration
# ---------------------------------------------------------------------------


def _make_prompt(tmp_path: Path, name: str = "test.md") -> Path:
    p = tmp_path / name
    p.write_text("do stuff", encoding="utf-8")
    return p


def test_parse_sub_task_with_must_set(tmp_path):
    prompt = _make_prompt(tmp_path)
    data = {
        "id": "summarize",
        "prompt": str(prompt),
        "must_set": [":pr-body"],
    }
    result = parse_sub_task("ex", 1, data, tmp_path, set())
    assert result.must_set == [":pr-body"]


def test_parse_sub_task_must_set_with_wait_for_signal(tmp_path):
    data = {
        "id": "wait",
        "wait_for_signal": "some.signal",
        "routes": [{"when": {"label": "ok"}, "continue": True}],
        "must_set": [":key"],
    }
    with pytest.raises(PropagateError, match="wait_for_signal.*must not have 'must_set'"):
        parse_sub_task("ex", 1, data, tmp_path, set(), signal_configs={"some.signal": None})


def test_parse_sub_task_without_must_set(tmp_path):
    prompt = _make_prompt(tmp_path)
    data = {"id": "impl", "prompt": str(prompt)}
    result = parse_sub_task("ex", 1, data, tmp_path, set())
    assert result.must_set == []


# ---------------------------------------------------------------------------
# validate_must_set_keys
# ---------------------------------------------------------------------------


def _make_runtime_context(context_root: Path, execution_name: str = "my-exec") -> RuntimeContext:
    return RuntimeContext(
        agent_command="echo",
        context_sources={},
        active_signal=None,
        initialized_signal_context_dirs=set(),
        working_dir=Path("."),
        context_root=context_root,
        execution_name=execution_name,
        task_id="summarize",
        git_state=GitRunState(),
    )


def _make_sub_task(must_set: list[str]) -> SubTaskConfig:
    return SubTaskConfig(
        task_id="summarize",
        prompt_path=None,
        before=[],
        after=[],
        on_failure=[],
        must_set=must_set,
    )


def test_validate_must_set_passes(tmp_path):
    rc = _make_runtime_context(tmp_path)
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":pr-body", "some body")
    sub_task = _make_sub_task([":pr-body"])
    validate_must_set_keys(sub_task, rc)


def test_validate_must_set_missing_key(tmp_path):
    rc = _make_runtime_context(tmp_path)
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    sub_task = _make_sub_task([":pr-body"])
    with pytest.raises(PropagateError, match=":pr-body"):
        validate_must_set_keys(sub_task, rc)


def test_validate_must_set_empty_value(tmp_path):
    rc = _make_runtime_context(tmp_path)
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":pr-body", "")
    sub_task = _make_sub_task([":pr-body"])
    with pytest.raises(PropagateError, match=":pr-body"):
        validate_must_set_keys(sub_task, rc)


def test_validate_must_set_partial_missing(tmp_path):
    rc = _make_runtime_context(tmp_path)
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":key-a", "value")
    sub_task = _make_sub_task([":key-a", ":key-b"])
    with pytest.raises(PropagateError, match=":key-b"):
        validate_must_set_keys(sub_task, rc)


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------


def test_append_must_set_notice():
    result = append_must_set_notice("prompt text\n", [":pr-body", ":pr-title"])
    assert "## Required Context Keys" in result
    assert "- `:pr-body`" in result
    assert "- `:pr-title`" in result
    assert "propagate context set" in result


def test_build_sub_task_prompt_no_must_set_section_when_none(tmp_path):
    """When must_set is None (default), no section is injected."""
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("do stuff\n", encoding="utf-8")
    rc = _make_runtime_context(tmp_path)
    result = build_sub_task_prompt(prompt_path, "summarize", rc, must_set=None)
    assert "Required Context Keys" not in result


def test_build_sub_task_prompt_with_must_set(tmp_path):
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("do stuff\n", encoding="utf-8")
    rc = _make_runtime_context(tmp_path)
    result = build_sub_task_prompt(prompt_path, "summarize", rc, must_set=[":pr-body"])
    assert "## Required Context Keys" in result
    assert ":pr-body" in result


def test_build_sub_task_prompt_without_must_set(tmp_path):
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("do stuff\n", encoding="utf-8")
    rc = _make_runtime_context(tmp_path)
    result = build_sub_task_prompt(prompt_path, "summarize", rc)
    assert "Required Context Keys" not in result
