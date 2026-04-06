from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from propagate_app.errors import PropagateError
from propagate_app.git_repo import prepare_execution_branch


def _run_git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=check)


@pytest.fixture()
def repo_ctx(tmp_path: Path):
    repo = tmp_path / "repo"
    remote_repo = tmp_path / "remote.git"
    second_clone = tmp_path / "second"
    repo.mkdir()

    _run_git("init", "-b", "main", cwd=repo)
    _run_git("config", "user.name", "Propagate Tests", cwd=repo)
    _run_git("config", "user.email", "propagate@example.com", cwd=repo)
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote_repo)], cwd=tmp_path, check=True, capture_output=True)
    _run_git("remote", "add", "origin", str(remote_repo), cwd=repo)

    (repo / "artifact.txt").write_text("initial\n", encoding="utf-8")
    _run_git("add", "-A", cwd=repo)
    _run_git("commit", "-m", "initial commit", cwd=repo)
    _run_git("push", "--set-upstream", "origin", "main", cwd=repo)

    return repo, remote_repo, second_clone


def _clone_remote(remote_repo: Path, second_clone: Path) -> None:
    subprocess.run(["git", "clone", str(remote_repo), str(second_clone)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Second Clone"], cwd=second_clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "second@example.com"], cwd=second_clone, check=True, capture_output=True)


def test_prepare_execution_branch_fast_forwards_existing_branch(repo_ctx) -> None:
    repo, remote_repo, second_clone = repo_ctx
    _clone_remote(remote_repo, second_clone)

    (second_clone / "remote.txt").write_text("from remote\n", encoding="utf-8")
    _run_git("add", "-A", cwd=second_clone)
    _run_git("commit", "-m", "remote update", cwd=second_clone)
    _run_git("push", "origin", "main", cwd=second_clone)

    prepare_execution_branch("main", "main", "origin", True, "main", repo)

    remote_head = _run_git("rev-parse", "origin/main", cwd=repo).stdout.strip()
    local_head = _run_git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    assert local_head == remote_head
    assert (repo / "remote.txt").read_text(encoding="utf-8") == "from remote\n"


def test_prepare_execution_branch_fails_when_existing_branch_has_local_only_commits(repo_ctx) -> None:
    repo, _remote_repo, _second_clone = repo_ctx

    (repo / "local.txt").write_text("local only\n", encoding="utf-8")
    _run_git("add", "-A", cwd=repo)
    _run_git("commit", "-m", "local ahead commit", cwd=repo)

    with pytest.raises(PropagateError, match="local commit\\(s\\) not on 'origin/main'"):
        prepare_execution_branch("main", "main", "origin", True, "main", repo)

