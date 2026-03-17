"""Tests that .env files are excluded from git commits made by propagate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from propagate_app.git_publish import create_execution_commit


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git("init", cwd=repo)
    _run_git("config", "user.email", "test@test.com", cwd=repo)
    _run_git("config", "user.name", "Test", cwd=repo)
    # Initial commit so HEAD exists
    (repo / "README.md").write_text("init")
    _run_git("add", "README.md", cwd=repo)
    _run_git("commit", "-m", "init", cwd=repo)
    return repo


def test_commit_excludes_env_without_gitignore(git_repo: Path) -> None:
    """.env should not be committed even when no .gitignore exists."""
    (git_repo / ".env").write_text("SECRET=abc123")
    (git_repo / "app.py").write_text("print('hello')")

    create_execution_commit("test: add app", git_repo)

    result = _run_git("show", "--name-only", "--format=", "HEAD", cwd=git_repo)
    committed = result.stdout.strip().splitlines()

    assert "app.py" in committed
    assert ".env" not in committed


def test_commit_excludes_env_with_gitignore(git_repo: Path) -> None:
    """.env should not be committed when .gitignore covers it."""
    (git_repo / ".gitignore").write_text(".env\n")
    _run_git("add", ".gitignore", cwd=git_repo)
    _run_git("commit", "-m", "add gitignore", cwd=git_repo)

    (git_repo / ".env").write_text("SECRET=abc123")
    (git_repo / "app.py").write_text("print('hello')")

    create_execution_commit("test: add app", git_repo)

    result = _run_git("show", "--name-only", "--format=", "HEAD", cwd=git_repo)
    committed = result.stdout.strip().splitlines()

    assert "app.py" in committed
    assert ".env" not in committed


def test_commit_excludes_env_in_subdirectory(git_repo: Path) -> None:
    """Nested .env files should also be excluded."""
    subdir = git_repo / "config"
    subdir.mkdir()
    (subdir / ".env").write_text("DB_PASSWORD=secret")
    (git_repo / "server.py").write_text("import flask")

    create_execution_commit("test: add server", git_repo)

    result = _run_git("show", "--name-only", "--format=", "HEAD", cwd=git_repo)
    committed = result.stdout.strip().splitlines()

    assert "server.py" in committed
    assert ".env" not in committed
    assert "config/.env" not in committed
