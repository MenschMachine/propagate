"""Tests for git:pr handling when a PR already exists for the branch."""

import subprocess
from unittest.mock import patch

import pytest

from propagate_app.errors import PropagateError
from propagate_app.git_publish import create_pull_request
from propagate_app.models import GitPrConfig


def _make_completed_process(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_pr_already_exists_fetches_existing_url(tmp_path):
    """When gh pr create says 'already exists', fetch and return existing PR URL."""
    pr_config = GitPrConfig(base="main", draft=False)

    create_result = _make_completed_process(1, stderr="a pull request for branch 'feat/x' into branch 'main' already exists")
    view_result = _make_completed_process(0, stdout="https://github.com/org/repo/pull/99\n")

    with patch("propagate_app.git_publish.run_process_command", side_effect=[create_result, view_result]) as mock_run:
        url = create_pull_request(pr_config, "main", "feat/x", "title", "body", tmp_path)

    assert url == "https://github.com/org/repo/pull/99"
    assert mock_run.call_count == 2


def test_pr_create_other_failure_raises(tmp_path):
    """When gh pr create fails for a reason other than 'already exists', raise."""
    pr_config = GitPrConfig(base="main", draft=False)

    create_result = _make_completed_process(1, stderr="some other error")

    with patch("propagate_app.git_publish.run_process_command", return_value=create_result):
        with pytest.raises(PropagateError, match="Failed to create pull request"):
            create_pull_request(pr_config, "main", "feat/x", "title", "body", tmp_path)


def test_pr_create_success_returns_url(tmp_path):
    """Normal success returns the URL from stdout."""
    pr_config = GitPrConfig(base="main", draft=False)

    create_result = _make_completed_process(0, stdout="https://github.com/org/repo/pull/42\n")

    with patch("propagate_app.git_publish.run_process_command", return_value=create_result):
        url = create_pull_request(pr_config, "main", "feat/x", "title", "body", tmp_path)

    assert url == "https://github.com/org/repo/pull/42"
