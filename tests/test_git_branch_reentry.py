"""Tests for git:branch re-entry — skip when already on execution branch."""

from pathlib import Path
from unittest.mock import patch

from propagate_app.git_runtime import git_do_branch
from propagate_app.models import (
    GitBranchConfig,
    GitCommitConfig,
    GitConfig,
    GitRunState,
    RuntimeContext,
)


def _make_runtime_context(context_root: Path, selected_branch: str | None = None) -> RuntimeContext:
    return RuntimeContext(
        agents={"default": "echo"},
        default_agent="default",
        context_sources={},
        active_signal=None,
        initialized_signal_context_dirs=set(),
        working_dir=Path("."),
        context_root=context_root,
        execution_name="my-exec",
        task_id="",
        git_state=GitRunState(selected_branch=selected_branch),
    )


def _make_git_config() -> GitConfig:
    return GitConfig(
        branch=GitBranchConfig(name="feat/test", base="main", reuse=True),
        commit=GitCommitConfig(message_source=None, message_key=":msg"),
        push=None,
        pr=None,
    )


def test_git_do_branch_skips_on_reentry(tmp_path):
    """When selected_branch is already set (re-entry via goto), git:branch should skip preparation."""
    rc = _make_runtime_context(tmp_path, selected_branch="feat/test")
    git_config = _make_git_config()

    with patch("propagate_app.git_runtime.prepare_git_execution") as mock_prepare:
        git_do_branch("my-exec", git_config, rc)
        mock_prepare.assert_not_called()

    assert rc.git_state.selected_branch == "feat/test"


def test_git_do_branch_runs_normally_on_first_entry(tmp_path):
    """When selected_branch is None (first entry), git:branch should run preparation."""
    from propagate_app.models import PreparedGitExecution

    rc = _make_runtime_context(tmp_path, selected_branch=None)
    git_config = _make_git_config()
    prepared = PreparedGitExecution(starting_branch="main", selected_branch="feat/test")

    with patch("propagate_app.git_runtime.prepare_git_execution", return_value=prepared) as mock_prepare:
        git_do_branch("my-exec", git_config, rc)
        mock_prepare.assert_called_once()

    assert rc.git_state.selected_branch == "feat/test"
