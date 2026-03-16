"""Tests that .env files are excluded from git commits made by propagate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


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


def test_git_add_excludes_env(git_repo: Path) -> None:
    """git add -A -- . :!.env should stage normal files but not .env."""
    (git_repo / ".env").write_text("SECRET=abc123")
    (git_repo / "app.py").write_text("print('hello')")

    _run_git("add", "-A", "--", ".", ":!.env", ":!**/.env", cwd=git_repo)

    result = _run_git("diff", "--cached", "--name-only", cwd=git_repo)
    staged = result.stdout.strip().splitlines()

    assert "app.py" in staged
    assert ".env" not in staged


def test_git_add_excludes_env_even_without_gitignore(git_repo: Path) -> None:
    """The pathspec exclude works regardless of .gitignore presence."""
    # Make sure there is no .gitignore
    gitignore = git_repo / ".gitignore"
    if gitignore.exists():
        gitignore.unlink()

    (git_repo / ".env").write_text("API_KEY=secret")
    (git_repo / "main.py").write_text("import os")

    _run_git("add", "-A", "--", ".", ":!.env", ":!**/.env", cwd=git_repo)

    result = _run_git("diff", "--cached", "--name-only", cwd=git_repo)
    staged = result.stdout.strip().splitlines()

    assert "main.py" in staged
    assert ".env" not in staged


def test_git_add_excludes_env_in_subdirectory(git_repo: Path) -> None:
    """Nested .env files should also be excluded."""
    subdir = git_repo / "config"
    subdir.mkdir()
    (subdir / ".env").write_text("DB_PASSWORD=secret")
    (git_repo / "server.py").write_text("import flask")

    _run_git("add", "-A", "--", ".", ":!.env", ":!**/.env", cwd=git_repo)

    result = _run_git("diff", "--cached", "--name-only", cwd=git_repo)
    staged = result.stdout.strip().splitlines()

    assert "server.py" in staged
    assert ".env" not in staged
    assert "config/.env" not in staged
