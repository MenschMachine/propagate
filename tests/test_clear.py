import yaml

from propagate_app.cli import main
from propagate_app.context_store import get_context_root
from propagate_app.run_state import state_file_path


def _write_config(tmp_path):
    config = {
        "version": "6",
        "agent": {"command": "echo {prompt_file}"},
        "repositories": {"repo": {"path": str(tmp_path / "repo")}},
        "executions": {
            "default": {
                "repository": "repo",
                "sub_tasks": [{"id": "t1"}],
            },
        },
    }
    (tmp_path / "repo").mkdir(exist_ok=True)
    config_path = tmp_path / "propagate.yaml"
    config_path.write_text(yaml.dump(config))
    return config_path


def _create_context(config_path):
    context_root = get_context_root(config_path)
    context_root.mkdir(parents=True)
    (context_root / "some-key").write_text("some-value")
    return context_root


def _create_state(config_path, cloned_repos=None):
    state_path = state_file_path(config_path)
    data = {"initial_execution": "default"}
    if cloned_repos:
        data["cloned_repos"] = {name: str(p) for name, p in cloned_repos.items()}
    state_path.write_text(yaml.dump(data))
    return state_path


def test_clear_both_context_and_state(tmp_path):
    config_path = _write_config(tmp_path)
    context_root = _create_context(config_path)
    state_path = _create_state(config_path)

    result = main(["clear", "--config", str(config_path)])

    assert result == 0
    assert not context_root.exists()
    assert not state_path.exists()


def test_clear_when_nothing_exists(tmp_path):
    config_path = _write_config(tmp_path)

    result = main(["clear", "--config", str(config_path)])

    assert result == 0


def test_clear_only_context(tmp_path):
    config_path = _write_config(tmp_path)
    context_root = _create_context(config_path)

    result = main(["clear", "--config", str(config_path)])

    assert result == 0
    assert not context_root.exists()


def test_clear_only_state(tmp_path):
    config_path = _write_config(tmp_path)
    state_path = _create_state(config_path)

    result = main(["clear", "--config", str(config_path)])

    assert result == 0
    assert not state_path.exists()


def test_clear_missing_config(tmp_path):
    result = main(["clear", "--config", str(tmp_path / "nonexistent.yaml")])

    assert result == 1


def test_clear_respects_context_root_env(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    custom_root = tmp_path / "custom-context"
    custom_root.mkdir()
    (custom_root / "key").write_text("value")
    monkeypatch.setenv("PROPAGATE_CONTEXT_ROOT", str(custom_root))

    result = main(["clear", "--config", str(config_path)])

    assert result == 0
    assert not custom_root.exists()
    # Default location should not have been touched
    assert not get_context_root(config_path).exists()


def test_clear_force_deletes_cloned_repos(tmp_path):
    config_path = _write_config(tmp_path)
    clone_dir = tmp_path / "propagate-repo-abc123"
    clone_dir.mkdir()
    (clone_dir / "file.txt").write_text("content")
    _create_state(config_path, cloned_repos={"myrepo": clone_dir})

    result = main(["clear", "--config", str(config_path), "-f"])

    assert result == 0
    assert not clone_dir.exists()


def test_clear_force_skips_non_propagate_dirs(tmp_path):
    config_path = _write_config(tmp_path)
    safe_dir = tmp_path / "my-important-repo"
    safe_dir.mkdir()
    (safe_dir / "file.txt").write_text("do not delete")
    _create_state(config_path, cloned_repos={"myrepo": safe_dir})

    result = main(["clear", "--config", str(config_path), "-f"])

    assert result == 0
    assert safe_dir.exists()
    assert (safe_dir / "file.txt").read_text() == "do not delete"


def test_clear_without_force_leaves_cloned_repos(tmp_path):
    config_path = _write_config(tmp_path)
    clone_dir = tmp_path / "propagate-repo-abc123"
    clone_dir.mkdir()
    _create_state(config_path, cloned_repos={"myrepo": clone_dir})

    result = main(["clear", "--config", str(config_path)])

    assert result == 0
    assert clone_dir.exists()


def test_clear_force_no_state_file(tmp_path):
    config_path = _write_config(tmp_path)
    _create_context(config_path)

    result = main(["clear", "--config", str(config_path), "-f"])

    assert result == 0


def test_clear_force_continues_after_delete_failure(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    clone_a = tmp_path / "propagate-repo-aaa"
    clone_b = tmp_path / "propagate-repo-bbb"
    clone_a.mkdir()
    clone_b.mkdir()
    _create_state(config_path, cloned_repos={"a": clone_a, "b": clone_b})

    import shutil
    original_rmtree = shutil.rmtree

    def failing_rmtree(path, *args, **kwargs):
        if str(path) == str(clone_a):
            raise OSError("permission denied")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", failing_rmtree)

    result = main(["clear", "--config", str(config_path), "-f"])

    assert result == 0
    assert clone_a.exists()  # failed to delete
    assert not clone_b.exists()  # still deleted
