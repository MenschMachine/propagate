"""Tests for PR title/body from context keys (title_key, body_key in git.pr config)."""

from pathlib import Path

import pytest

from propagate_app.config_git import parse_git_pr_config
from propagate_app.context_store import ensure_context_dir, write_context_value
from propagate_app.errors import PropagateError
from propagate_app.git_runtime import load_pr_title_body
from propagate_app.models import ActiveSignal, GitPrConfig, GitRunState, RuntimeContext, ScopedContextKey

# ---------------------------------------------------------------------------
# Parse tests
# ---------------------------------------------------------------------------


def test_parse_title_key_valid():
    result = parse_git_pr_config("ex", {"title_key": ":pr-title"})
    assert result is not None
    assert result.title_key == ScopedContextKey(key=":pr-title")
    assert result.body_key is None


def test_parse_body_key_valid():
    result = parse_git_pr_config("ex", {"body_key": ":pr-body"})
    assert result is not None
    assert result.body_key == ScopedContextKey(key=":pr-body")
    assert result.title_key is None


def test_parse_both_keys():
    result = parse_git_pr_config("ex", {"title_key": ":pr-title", "body_key": ":pr-body"})
    assert result is not None
    assert result.title_key == ScopedContextKey(key=":pr-title")
    assert result.body_key == ScopedContextKey(key=":pr-body")


def test_parse_templates():
    result = parse_git_pr_config("ex", {"title_template": "title {signal[pr_number]}", "body_template": "body"})
    assert result is not None
    assert result.title_template == "title {signal[pr_number]}"
    assert result.body_template == "body"


def test_parse_title_key_missing_colon():
    with pytest.raises(PropagateError, match="':'-prefixed"):
        parse_git_pr_config("ex", {"title_key": "pr-title"})


def test_parse_body_key_missing_colon():
    with pytest.raises(PropagateError, match="':'-prefixed"):
        parse_git_pr_config("ex", {"body_key": "pr-body"})


def test_parse_no_keys_defaults_none():
    result = parse_git_pr_config("ex", {})
    assert result is not None
    assert result.title_key is None
    assert result.body_key is None


def test_parse_title_key_and_template_conflict():
    with pytest.raises(PropagateError, match="at most one of 'title_key' or 'title_template'"):
        parse_git_pr_config("ex", {"title_key": ":pr-title", "title_template": "title"})


# ---------------------------------------------------------------------------
# Runtime tests
# ---------------------------------------------------------------------------


def _make_runtime_context(context_root: Path) -> RuntimeContext:
    return RuntimeContext(
        agents={"default": "echo"},
        default_agent="default",
        context_sources={},
        active_signal=None,
        initialized_signal_context_dirs=set(),
        working_dir=Path("."),
        context_root=context_root,
        execution_name="my-exec",
        task_id="task-1",
        git_state=GitRunState(),
    )


def test_load_pr_title_body_defaults(tmp_path):
    """Without keys set, split commit message as before."""
    pr_config = GitPrConfig(base=None, draft=False)
    rc = _make_runtime_context(tmp_path)
    title, body = load_pr_title_body(pr_config, "Subject line\n\nBody text", rc)
    assert title == "Subject line"
    assert body == "\nBody text"


def test_load_pr_title_from_context_key(tmp_path):
    """title_key set: title from context store, body from commit message."""
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":pr-title", "Context title")

    pr_config = GitPrConfig(base=None, draft=False, title_key=":pr-title")
    rc = _make_runtime_context(tmp_path)
    title, body = load_pr_title_body(pr_config, "Commit subject\n\nCommit body", rc)
    assert title == "Context title"
    assert body == "\nCommit body"


def test_load_pr_body_from_context_key(tmp_path):
    """body_key set: body from context store, title from commit message."""
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":pr-body", "Context body text")

    pr_config = GitPrConfig(base=None, draft=False, body_key=":pr-body")
    rc = _make_runtime_context(tmp_path)
    title, body = load_pr_title_body(pr_config, "Commit subject\n\nCommit body", rc)
    assert title == "Commit subject"
    assert body == "Context body text"


def test_load_pr_title_key_missing_raises(tmp_path):
    """title_key configured but key not written → PropagateError."""
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    # deliberately do not write :pr-title

    pr_config = GitPrConfig(base=None, draft=False, title_key=":pr-title")
    rc = _make_runtime_context(tmp_path)
    with pytest.raises(PropagateError, match=":pr-title"):
        load_pr_title_body(pr_config, "Subject\n\nBody", rc)


def test_load_pr_body_key_missing_raises(tmp_path):
    """body_key configured but key not written → PropagateError."""
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)

    pr_config = GitPrConfig(base=None, draft=False, body_key=":pr-body")
    rc = _make_runtime_context(tmp_path)
    with pytest.raises(PropagateError, match=":pr-body"):
        load_pr_title_body(pr_config, "Subject\n\nBody", rc)


def test_load_pr_both_from_context_keys(tmp_path):
    """Both keys set: both from context store."""
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":pr-title", "Override title")
    write_context_value(context_dir, ":pr-body", "Override body")

    pr_config = GitPrConfig(base=None, draft=False, title_key=":pr-title", body_key=":pr-body")
    rc = _make_runtime_context(tmp_path)
    title, body = load_pr_title_body(pr_config, "Commit subject\n\nCommit body", rc)
    assert title == "Override title"
    assert body == "Override body"


def test_load_pr_both_from_templates(tmp_path):
    rc = RuntimeContext(
        agents={"default": "echo"},
        default_agent="default",
        context_sources={},
        active_signal=ActiveSignal(signal_type="pull_request.labeled", payload={"pr_number": 42}, source="test"),
        initialized_signal_context_dirs=set(),
        working_dir=Path("."),
        context_root=tmp_path,
        execution_name="my-exec",
        task_id="",
        git_state=GitRunState(),
    )
    pr_config = GitPrConfig(
        base=None,
        draft=False,
        title_template="PR for #{signal[pr_number]}",
        body_template="Implements PR #{signal[pr_number]}",
    )
    title, body = load_pr_title_body(pr_config, "Commit subject\n\nCommit body", rc)
    assert title == "PR for #42"
    assert body == "Implements PR #42"
