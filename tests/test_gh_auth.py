from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from propagate_app.models import RepositoryConfig
from propagate_app.repo_clone import _ssh_url_to_https, clone_single_repository

# --- _ssh_url_to_https ---

@pytest.mark.parametrize("ssh_url,expected", [
    ("git@github.com:owner/repo.git", "https://github.com/owner/repo.git"),
    ("git@github.com:owner/repo", "https://github.com/owner/repo"),
    ("git@gitlab.com:group/project.git", "https://gitlab.com/group/project.git"),
    ("git@bitbucket.org:team/repo.git", "https://bitbucket.org/team/repo.git"),
])
def test_ssh_url_converted_to_https(ssh_url, expected):
    assert _ssh_url_to_https(ssh_url) == expected


@pytest.mark.parametrize("url", [
    "https://github.com/owner/repo.git",
    "https://github.com/owner/repo",
    "http://gitlab.com/group/project.git",
    "/local/path/to/repo",
])
def test_https_and_other_urls_pass_through(url):
    assert _ssh_url_to_https(url) == url


# --- clone_single_repository ---

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


def test_clone_converts_ssh_url_to_https(tmp_path):
    """clone_single_repository should convert SSH URLs to HTTPS before cloning."""
    bare = _create_bare_repo(tmp_path)
    # Use the bare repo path as the "HTTPS" URL so the clone actually works,
    # but verify the SSH-to-HTTPS conversion is called.
    ssh_url = "git@github.com:owner/repo.git"
    repo = RepositoryConfig(name="test", path=None, url=ssh_url)

    with patch("propagate_app.repo_clone._ssh_url_to_https", return_value=str(bare)) as mock_convert:
        result = clone_single_repository("test", repo)

    mock_convert.assert_called_once_with(ssh_url)
    try:
        assert result.is_dir()
        assert (result / "README.md").exists()
    finally:
        shutil.rmtree(result, ignore_errors=True)


def test_credential_helper_configured_after_clone(tmp_path):
    """After cloning, the repo should have the gh credential helper configured."""
    bare = _create_bare_repo(tmp_path)
    repo = RepositoryConfig(name="test", path=None, url=str(bare))

    result = clone_single_repository("test", repo)
    try:
        output = subprocess.run(
            ["git", "config", "credential.helper"],
            cwd=str(result), capture_output=True, text=True, check=True,
        )
        assert output.stdout.strip() == "!gh auth git-credential"
    finally:
        shutil.rmtree(result, ignore_errors=True)


def test_credential_helper_configured_on_reuse(tmp_path):
    """Reusing an existing clone should also configure the credential helper."""
    # Create a git repo to reuse
    reuse_dir = tmp_path / "existing"
    reuse_dir.mkdir()
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", str(reuse_dir)],
        check=True, capture_output=True,
    )

    repo = RepositoryConfig(name="test", path=None, url="https://example.com/repo.git")
    result = clone_single_repository("test", repo, existing_path=reuse_dir)

    assert result == reuse_dir
    output = subprocess.run(
        ["git", "config", "credential.helper"],
        cwd=str(result), capture_output=True, text=True, check=True,
    )
    assert output.stdout.strip() == "!gh auth git-credential"
