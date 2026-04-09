"""Tests for git.branch.name_key — dynamic branch name from context."""

from pathlib import Path
from unittest.mock import patch

import pytest

from propagate_app.config_git import parse_git_branch_config
from propagate_app.context_store import ensure_context_dir, write_context_value
from propagate_app.errors import PropagateError
from propagate_app.git_repo import resolve_execution_branch_name
from propagate_app.git_runtime import git_do_branch
from propagate_app.models import (
    ActiveSignal,
    GitBranchConfig,
    GitCommitConfig,
    GitConfig,
    GitRunState,
    PreparedGitExecution,
    RuntimeContext,
    ScopedContextKey,
)

# ---------------------------------------------------------------------------
# Config parse tests
# ---------------------------------------------------------------------------


def test_parse_name_key_valid():
    result = parse_git_branch_config("ex", {"name_key": ":branch-name"})
    assert result.name_key == ScopedContextKey(key=":branch-name")
    assert result.name is None


def test_parse_name_key_missing_colon():
    with pytest.raises(PropagateError, match="':'-prefixed"):
        parse_git_branch_config("ex", {"name_key": "branch-name"})


def test_parse_name_and_name_key_mutual_exclusion():
    with pytest.raises(PropagateError, match="at most one of"):
        parse_git_branch_config("ex", {"name": "my-branch", "name_key": ":branch-name"})


def test_parse_name_template_valid():
    result = parse_git_branch_config("ex", {"name_template": "feat/{signal[pr_number]}"})
    assert result.name_template == "feat/{signal[pr_number]}"
    assert result.name is None
    assert result.name_key is None


def test_parse_name_key_with_base():
    result = parse_git_branch_config("ex", {"name_key": ":branch-name", "base": "main"})
    assert result.name_key == ScopedContextKey(key=":branch-name")
    assert result.base == "main"


def test_parse_no_name_no_name_key():
    result = parse_git_branch_config("ex", {})
    assert result.name is None
    assert result.name_key is None


# ---------------------------------------------------------------------------
# Runtime resolve tests
# ---------------------------------------------------------------------------


def test_resolve_branch_name_falls_back_to_default(tmp_path):
    """Without name_key, uses name or default."""
    config = GitBranchConfig(name=None, base=None, reuse=True)
    result = resolve_execution_branch_name(config, "my-exec", tmp_path)
    assert result == "propagate/my-exec"


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


def test_git_do_branch_resolves_name_key(tmp_path):
    """git_do_branch reads branch name from context when name_key is set."""
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":branch-name", "feat/dynamic")

    git_config = GitConfig(
        branch=GitBranchConfig(name=None, base="main", reuse=True, name_key=":branch-name"),
        commit=GitCommitConfig(message_source=None, message_key=":msg"),
        push=None,
        pr=None,
    )
    rc = _make_runtime_context(tmp_path)
    prepared = PreparedGitExecution(starting_branch="main", selected_branch="feat/dynamic")

    with patch("propagate_app.git_runtime.prepare_git_execution", return_value=prepared) as mock_prepare:
        git_do_branch("my-exec", git_config, rc)
        # Verify the branch config passed to prepare_git_execution has name resolved, name_key cleared
        called_config = mock_prepare.call_args[0][1]
        assert called_config.name == "feat/dynamic"
        assert called_config.name_key is None

    assert rc.git_state.selected_branch == "feat/dynamic"


def test_git_do_branch_name_key_missing_raises(tmp_path):
    """git_do_branch raises when name_key context value is missing."""
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)

    git_config = GitConfig(
        branch=GitBranchConfig(name=None, base="main", reuse=True, name_key=":branch-name"),
        commit=GitCommitConfig(message_source=None, message_key=":msg"),
        push=None,
        pr=None,
    )
    rc = _make_runtime_context(tmp_path)

    with pytest.raises(PropagateError, match=":branch-name"):
        git_do_branch("my-exec", git_config, rc)


def test_git_do_branch_resolves_name_template_from_signal(tmp_path):
    git_config = GitConfig(
        branch=GitBranchConfig(name=None, base="main", reuse=True, name_template="feat/pr-{signal[pr_number]}"),
        commit=GitCommitConfig(message_source=None, message_key=":msg"),
        push=None,
        pr=None,
    )
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
    prepared = PreparedGitExecution(starting_branch="main", selected_branch="feat/pr-42")

    with patch("propagate_app.git_runtime.prepare_git_execution", return_value=prepared) as mock_prepare:
        git_do_branch("my-exec", git_config, rc)
        called_config = mock_prepare.call_args[0][1]
        assert called_config.name == "feat/pr-42"
        assert called_config.name_key is None
        assert called_config.name_template is None
