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


def _create_state(config_path):
    state_path = state_file_path(config_path)
    state_path.write_text("initial_execution: default\n")
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
