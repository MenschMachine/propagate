"""Tests for GITHUB_TOKEN injection into clone URLs."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from propagate_app.models import RepositoryConfig
from propagate_app.repo_clone import _inject_token_into_url, clone_single_repository

# --- _inject_token_into_url ---


def test_injects_token_into_https_github_url():
    url = "https://github.com/owner/repo.git"
    assert _inject_token_into_url(url, "tok123") == "https://x-access-token:tok123@github.com/owner/repo.git"


def test_injects_token_into_https_url_without_dotgit():
    url = "https://github.com/owner/repo"
    assert _inject_token_into_url(url, "tok123") == "https://x-access-token:tok123@github.com/owner/repo"


def test_no_injection_when_token_is_none():
    url = "https://github.com/owner/repo.git"
    assert _inject_token_into_url(url, None) == url


def test_no_injection_when_token_is_empty():
    url = "https://github.com/owner/repo.git"
    assert _inject_token_into_url(url, "") == url


def test_no_injection_for_non_https_url():
    url = "/local/path/to/repo"
    assert _inject_token_into_url(url, "tok123") == url


def test_no_injection_when_url_already_has_credentials():
    url = "https://user:pass@github.com/owner/repo.git"
    assert _inject_token_into_url(url, "tok123") == url


# --- clone uses GITHUB_TOKEN ---


def _create_bare_repo(workspace: Path) -> Path:
    bare_dir = workspace / "bare.git"
    bare_dir.mkdir()
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "--bare", str(bare_dir)],
        check=True, capture_output=True,
    )
    work_dir = workspace / "work"
    work_dir.mkdir()
    subprocess.run(["git", "clone", str(bare_dir), str(work_dir)], check=True, capture_output=True)
    (work_dir / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "."], cwd=str(work_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=t@t", "commit", "-m", "init"],
        cwd=str(work_dir), check=True, capture_output=True,
    )
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(work_dir), check=True, capture_output=True)
    shutil.rmtree(work_dir)
    return bare_dir


def test_clone_injects_token_from_env(tmp_path, monkeypatch):
    """When GITHUB_TOKEN is set, clone should inject it into the HTTPS URL."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
    repo = RepositoryConfig(name="test", path=None, url="https://github.com/owner/repo.git")

    with patch("propagate_app.repo_clone.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        clone_single_repository("test", repo)

    # The first subprocess.run call is the clone
    clone_call = mock_run.call_args_list[0]
    clone_cmd = clone_call[0][0]
    assert "x-access-token:ghp_test123@github.com" in clone_cmd[2]


def test_clone_no_token_uses_plain_url(tmp_path, monkeypatch):
    """When GITHUB_TOKEN is not set, clone should use the plain URL."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    repo = RepositoryConfig(name="test", path=None, url="https://github.com/owner/repo.git")

    with patch("propagate_app.repo_clone.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        clone_single_repository("test", repo)

    clone_call = mock_run.call_args_list[0]
    clone_cmd = clone_call[0][0]
    assert clone_cmd[2] == "https://github.com/owner/repo.git"
