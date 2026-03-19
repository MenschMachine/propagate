from pathlib import Path

import pytest

from propagate_app.config_git import parse_git_commit_config
from propagate_app.context_store import ensure_context_dir, write_context_value
from propagate_app.errors import PropagateError
from propagate_app.git_publish import load_commit_message
from propagate_app.git_templates import render_git_template
from propagate_app.models import ActiveSignal, GitCommitConfig, GitRunState, RuntimeContext


def _make_runtime_context(context_root: Path, active_signal: ActiveSignal | None = None) -> RuntimeContext:
    return RuntimeContext(
        agent_command="echo",
        context_sources={},
        active_signal=active_signal,
        initialized_signal_context_dirs=set(),
        working_dir=Path("."),
        context_root=context_root,
        execution_name="my-exec",
        task_id="",
        git_state=GitRunState(),
    )


def test_parse_message_template_valid():
    result = parse_git_commit_config("ex", {"message_template": "feat: PR #{signal[pr_number]}"}, set())
    assert result.message_template == "feat: PR #{signal[pr_number]}"
    assert result.message_key is None
    assert result.message_source is None


def test_parse_message_template_is_mutually_exclusive():
    with pytest.raises(PropagateError, match="exactly one of 'message_source', 'message_key', or 'message_template'"):
        parse_git_commit_config("ex", {"message_key": ":msg", "message_template": "feat"}, set())


def test_render_git_template_reads_scoped_context_and_signal(tmp_path):
    current_context_dir = tmp_path / "my-exec"
    other_context_dir = tmp_path / "other-exec"
    ensure_context_dir(current_context_dir)
    ensure_context_dir(other_context_dir)
    write_context_value(current_context_dir, ":current", "cur")
    write_context_value(other_context_dir, ":source-backend-pr-number", "17")

    rc = _make_runtime_context(
        tmp_path,
        active_signal=ActiveSignal(signal_type="pull_request.labeled", payload={"pr_number": 42}, source="test"),
    )

    rendered = render_git_template(
        "branch-{signal[pr_number]}-{context[:current]}-{context[other-exec][:source-backend-pr-number]}",
        rc,
    )
    assert rendered == "branch-42-cur-17"


def test_load_commit_message_from_template(tmp_path):
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":backend-pr-number", "31")

    rc = _make_runtime_context(tmp_path)
    commit_config = GitCommitConfig(
        message_source=None,
        message_key=None,
        message_template="feat: sync backend PR #{context[:backend-pr-number]}",
    )
    message = load_commit_message(commit_config, rc, "my-exec")
    assert message == "feat: sync backend PR #31"


def test_render_git_template_wraps_malformed_format_string(tmp_path):
    rc = _make_runtime_context(tmp_path)
    with pytest.raises(PropagateError, match="Invalid git template"):
        render_git_template("broken-{", rc)


def test_render_git_template_validates_context_keys_before_read(tmp_path):
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    (tmp_path / "secret").write_text("should-not-be-read", encoding="utf-8")

    rc = _make_runtime_context(tmp_path)
    with pytest.raises(PropagateError):
        render_git_template("value-{context[../secret]}", rc)


def test_render_git_template_rejects_invalid_scoped_context_paths(tmp_path):
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    (tmp_path / "other-exec").mkdir()

    rc = _make_runtime_context(tmp_path)
    with pytest.raises(PropagateError, match="must not contain '.' or '..'"):
        render_git_template("value-{context[../other-exec][:source-backend-pr-number]}", rc)
