"""Tests for git.pr.number_key — capture PR number into context."""

from pathlib import Path
from unittest.mock import patch

import pytest

from propagate_app.config_git import parse_git_pr_config
from propagate_app.context_store import ensure_context_dir, read_context_value
from propagate_app.errors import PropagateError
from propagate_app.git_runtime import create_execution_git_pr
from propagate_app.models import (
    GitBranchConfig,
    GitCommitConfig,
    GitConfig,
    GitPrConfig,
    GitPushConfig,
    GitRunState,
    PreparedGitExecution,
    RuntimeContext,
)

# ---------------------------------------------------------------------------
# Config parse tests
# ---------------------------------------------------------------------------


def test_parse_number_key_valid():
    result = parse_git_pr_config("ex", {"number_key": ":pr-number"})
    assert result is not None
    assert result.number_key == ":pr-number"


def test_parse_number_key_missing_colon():
    with pytest.raises(PropagateError, match="':'-prefixed"):
        parse_git_pr_config("ex", {"number_key": "pr-number"})


def test_parse_number_key_with_other_keys():
    result = parse_git_pr_config("ex", {"body_key": ":body", "number_key": ":pr-number"})
    assert result is not None
    assert result.body_key == ":body"
    assert result.number_key == ":pr-number"


def test_parse_no_number_key_defaults_none():
    result = parse_git_pr_config("ex", {})
    assert result is not None
    assert result.number_key is None


# ---------------------------------------------------------------------------
# Runtime tests
# ---------------------------------------------------------------------------


def _make_runtime_context(context_root: Path) -> RuntimeContext:
    return RuntimeContext(
        agent_command="echo",
        context_sources={},
        active_signal=None,
        initialized_signal_context_dirs=set(),
        working_dir=Path("."),
        context_root=context_root,
        execution_name="my-exec",
        task_id="",
        git_state=GitRunState(),
    )


def test_pr_number_stored_in_context(tmp_path):
    """When number_key is set and PR is created, the PR number is written to context."""
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)

    pr_config = GitPrConfig(base="main", draft=False, number_key=":pr-number")
    git_config = GitConfig(
        branch=GitBranchConfig(name="feat/x", base="main", reuse=True),
        commit=GitCommitConfig(message_source=None, message_key=":msg"),
        push=GitPushConfig(remote="origin"),
        pr=pr_config,
    )
    prepared = PreparedGitExecution(starting_branch="main", selected_branch="feat/x")
    rc = _make_runtime_context(tmp_path)

    with patch("propagate_app.git_runtime.create_pull_request", return_value="https://github.com/org/repo/pull/42"):
        create_execution_git_pr("my-exec", git_config, prepared, "Subject\n\nBody", rc)

    value = read_context_value(context_dir, ":pr-number")
    assert value == "42"


def test_pr_number_not_stored_without_key(tmp_path):
    """When number_key is not set, no context key is written."""
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)

    pr_config = GitPrConfig(base="main", draft=False)
    git_config = GitConfig(
        branch=GitBranchConfig(name="feat/x", base="main", reuse=True),
        commit=GitCommitConfig(message_source=None, message_key=":msg"),
        push=GitPushConfig(remote="origin"),
        pr=pr_config,
    )
    prepared = PreparedGitExecution(starting_branch="main", selected_branch="feat/x")
    rc = _make_runtime_context(tmp_path)

    with patch("propagate_app.git_runtime.create_pull_request", return_value="https://github.com/org/repo/pull/42"):
        create_execution_git_pr("my-exec", git_config, prepared, "Subject\n\nBody", rc)

    assert not (context_dir / ":pr-number").exists()


def test_pr_number_invalid_url_raises(tmp_path):
    """When the PR URL doesn't end in a number, a PropagateError is raised."""
    context_dir = tmp_path / "my-exec"
    ensure_context_dir(context_dir)

    pr_config = GitPrConfig(base="main", draft=False, number_key=":pr-number")
    git_config = GitConfig(
        branch=GitBranchConfig(name="feat/x", base="main", reuse=True),
        commit=GitCommitConfig(message_source=None, message_key=":msg"),
        push=GitPushConfig(remote="origin"),
        pr=pr_config,
    )
    prepared = PreparedGitExecution(starting_branch="main", selected_branch="feat/x")
    rc = _make_runtime_context(tmp_path)

    with patch("propagate_app.git_runtime.create_pull_request", return_value="https://github.com/org/repo/pull/not-a-number"):
        with pytest.raises(PropagateError, match="Could not extract PR number"):
            create_execution_git_pr("my-exec", git_config, prepared, "Subject\n\nBody", rc)
