"""Tests for persistent bare-repo clone cache."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from propagate_app.config_load import load_config
from propagate_app.constants import BARE_CLONE_MARKER_FILENAME
from propagate_app.models import RepositoryConfig
from propagate_app.repo_clone import (
    _bare_cache_path,
    _sanitize_clone_name,
    clone_single_repository,
    is_propagate_bare_cache,
)


@pytest.fixture()
def repo():
    return RepositoryConfig(name="myrepo", path=None, url="https://example.com/org/myrepo.git")


@pytest.fixture()
def minimal_config_data():
    return {
        "version": "6",
        "agent": {"command": "echo {prompt_file}"},
        "repositories": {"r": {"path": "."}},
        "executions": {
            "e": {
                "repository": "r",
                "sub_tasks": [{"id": "t", "prompt": None}],
            }
        },
    }


def _make_bare_cache(cache_dir: Path, name: str) -> Path:
    """Create a fake bare cache directory with the marker file."""
    bare_path = cache_dir / f"{_sanitize_clone_name(name)}.git"
    bare_path.mkdir(parents=True)
    (bare_path / BARE_CLONE_MARKER_FILENAME).write_text("", encoding="utf-8")
    return bare_path


def test_bare_cache_path_naming(tmp_path):
    cache_dir = tmp_path / "cache"
    result = _bare_cache_path(cache_dir, "my-repo")
    assert result == cache_dir / "my-repo.git"


def test_bare_cache_path_sanitizes_name(tmp_path):
    cache_dir = tmp_path / "cache"
    result = _bare_cache_path(cache_dir, "org/repo name")
    assert result == cache_dir / "org-repo-name.git"


def test_is_propagate_bare_cache_false_when_missing(tmp_path):
    assert is_propagate_bare_cache(tmp_path / "nonexistent") is False


def test_is_propagate_bare_cache_false_when_no_marker(tmp_path):
    d = tmp_path / "repo.git"
    d.mkdir()
    assert is_propagate_bare_cache(d) is False


def test_is_propagate_bare_cache_true_with_marker(tmp_path):
    d = tmp_path / "repo.git"
    d.mkdir()
    (d / BARE_CLONE_MARKER_FILENAME).write_text("", encoding="utf-8")
    assert is_propagate_bare_cache(d) is True


def test_cache_miss_creates_bare_and_clones_locally(tmp_path, repo, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cache_dir = tmp_path / "cache"

    with patch("propagate_app.repo_clone.subprocess.run") as mock_run:
        clone_single_repository("myrepo", repo, repo_cache_dir=cache_dir)

    calls = [c.args[0] for c in mock_run.call_args_list]
    # bare clone
    assert ["git", "clone", "--bare", repo.url, str(cache_dir / "myrepo.git")] in calls
    # strip token from bare remote
    assert ["git", "remote", "set-url", "origin", repo.url] in calls
    # local clone from bare
    bare_path = cache_dir / "myrepo.git"
    assert any(c[:2] == ["git", "clone"] and str(bare_path) in c for c in calls)
    # marker was written
    assert (cache_dir / "myrepo.git" / BARE_CLONE_MARKER_FILENAME).is_file()


def test_cache_miss_creates_cache_dir(tmp_path, repo, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cache_dir = tmp_path / "deep" / "cache"
    assert not cache_dir.exists()

    with patch("propagate_app.repo_clone.subprocess.run"):
        clone_single_repository("myrepo", repo, repo_cache_dir=cache_dir)

    assert cache_dir.is_dir()


def test_cache_hit_fetches_and_clones_locally(tmp_path, repo, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cache_dir = tmp_path / "cache"
    _make_bare_cache(cache_dir, "myrepo")

    with patch("propagate_app.repo_clone.subprocess.run") as mock_run:
        clone_single_repository("myrepo", repo, repo_cache_dir=cache_dir)

    calls = [c.args[0] for c in mock_run.call_args_list]
    # must NOT do a bare clone
    assert not any(c[:3] == ["git", "clone", "--bare"] for c in calls)
    # must fetch
    assert ["git", "fetch", "origin"] in calls
    # must do a local clone from bare path
    bare_path = cache_dir / "myrepo.git"
    assert any(c[:2] == ["git", "clone"] and str(bare_path) in c for c in calls)


def test_concurrent_calls_get_separate_working_dirs(tmp_path, repo, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cache_dir = tmp_path / "cache"

    with patch("propagate_app.repo_clone.subprocess.run"):
        dest1 = clone_single_repository("myrepo", repo, repo_cache_dir=cache_dir)
        dest2 = clone_single_repository("myrepo", repo, repo_cache_dir=cache_dir)

    assert dest1 != dest2
    assert dest1.parent == dest2.parent


def test_no_cache_when_repo_cache_dir_not_set(tmp_path, repo, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("PROPAGATE_CLONE_DIR", raising=False)

    with patch("propagate_app.repo_clone.subprocess.run") as mock_run:
        clone_single_repository("myrepo", repo, clone_dir=tmp_path)

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any(c[:3] == ["git", "clone", "--bare"] for c in calls)
    assert not any("fetch" in c for c in calls)
    # standard clone
    assert any(c[:2] == ["git", "clone"] for c in calls)


def test_config_parsing_repo_cache_dir_relative(tmp_path, minimal_config_data):
    minimal_config_data["repo_cache_dir"] = "cache"
    path = tmp_path / "propagate.yaml"
    path.write_text(yaml.dump(minimal_config_data))
    config = load_config(path)
    assert config.repo_cache_dir == (tmp_path / "cache").resolve()


def test_config_parsing_repo_cache_dir_absolute(tmp_path, minimal_config_data):
    abs_dir = tmp_path / "abs-cache"
    minimal_config_data["repo_cache_dir"] = str(abs_dir)
    path = tmp_path / "propagate.yaml"
    path.write_text(yaml.dump(minimal_config_data))
    config = load_config(path)
    assert config.repo_cache_dir == abs_dir


def test_config_parsing_repo_cache_dir_absent(tmp_path, minimal_config_data):
    path = tmp_path / "propagate.yaml"
    path.write_text(yaml.dump(minimal_config_data))
    config = load_config(path)
    assert config.repo_cache_dir == (tmp_path / ".repo-cache").resolve()


def test_env_clone_dir_bypasses_cache(tmp_path, repo, monkeypatch):
    """When PROPAGATE_CLONE_DIR is set, the bare cache is not used even if repo_cache_dir is set."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    env_dir = tmp_path / "env-clones"
    env_dir.mkdir()
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("PROPAGATE_CLONE_DIR", str(env_dir))

    with patch("propagate_app.repo_clone.subprocess.run") as mock_run:
        result = clone_single_repository("myrepo", repo, repo_cache_dir=cache_dir)

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any(c[:3] == ["git", "clone", "--bare"] for c in calls)
    assert str(result).startswith(str(env_dir))
