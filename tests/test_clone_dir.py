"""Tests for configurable clone temp directory."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from propagate_app.config_load import load_config
from propagate_app.constants import ENV_CLONE_DIR
from propagate_app.errors import PropagateError
from propagate_app.models import RepositoryConfig
from propagate_app.repo_clone import clone_single_repository


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


@pytest.fixture()
def config_file(tmp_path, minimal_config_data):
    path = tmp_path / "propagate.yaml"
    path.write_text(yaml.dump(minimal_config_data))
    return path


def test_yaml_parsing_clone_dir_relative(tmp_path, minimal_config_data):
    minimal_config_data["clone_dir"] = "clones"
    path = tmp_path / "propagate.yaml"
    path.write_text(yaml.dump(minimal_config_data))
    config = load_config(path)
    assert config.clone_dir == (tmp_path / "clones").resolve()


def test_yaml_parsing_clone_dir_absolute(tmp_path, minimal_config_data):
    abs_dir = tmp_path / "abs-clones"
    minimal_config_data["clone_dir"] = str(abs_dir)
    path = tmp_path / "propagate.yaml"
    path.write_text(yaml.dump(minimal_config_data))
    config = load_config(path)
    assert config.clone_dir == abs_dir


def test_yaml_parsing_clone_dir_absent(config_file):
    config = load_config(config_file)
    assert config.clone_dir is None


def test_env_var_overrides_config(tmp_path, monkeypatch):
    env_dir = tmp_path / "env-clones"
    env_dir.mkdir()
    config_dir = tmp_path / "cfg-clones"
    config_dir.mkdir()

    monkeypatch.setenv(ENV_CLONE_DIR, str(env_dir))
    repo = RepositoryConfig(name="r", path=None, url="https://example.com/repo.git")

    with patch("propagate_app.repo_clone.subprocess.run"):
        result = clone_single_repository("r", repo, clone_dir=config_dir)

    assert str(result).startswith(str(env_dir))


def test_config_value_used_when_no_env_var(tmp_path, monkeypatch):
    config_dir = tmp_path / "cfg-clones"
    config_dir.mkdir()

    monkeypatch.delenv(ENV_CLONE_DIR, raising=False)
    repo = RepositoryConfig(name="r", path=None, url="https://example.com/repo.git")

    with patch("propagate_app.repo_clone.subprocess.run"):
        result = clone_single_repository("r", repo, clone_dir=config_dir)

    assert str(result).startswith(str(config_dir))


def test_system_default_when_neither_set(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_CLONE_DIR, raising=False)
    repo = RepositoryConfig(name="r", path=None, url="https://example.com/repo.git")

    with patch("propagate_app.repo_clone.subprocess.run"):
        result = clone_single_repository("r", repo)

    assert str(result).startswith(tempfile.gettempdir())


def test_nonexistent_clone_dir_is_created(tmp_path, monkeypatch):
    clone_dir = tmp_path / "deep" / "nested" / "clones"
    monkeypatch.delenv(ENV_CLONE_DIR, raising=False)
    repo = RepositoryConfig(name="r", path=None, url="https://example.com/repo.git")

    with patch("propagate_app.repo_clone.subprocess.run"):
        result = clone_single_repository("r", repo, clone_dir=clone_dir)

    assert clone_dir.is_dir()
    assert str(result).startswith(str(clone_dir))


def test_unwritable_clone_dir_raises_propagate_error(tmp_path, monkeypatch):
    bad_path = Path("/dev/null/impossible")
    monkeypatch.delenv(ENV_CLONE_DIR, raising=False)
    repo = RepositoryConfig(name="r", path=None, url="https://example.com/repo.git")

    with pytest.raises(PropagateError, match="Cannot create clone directory"):
        clone_single_repository("r", repo, clone_dir=bad_path)
