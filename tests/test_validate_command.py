import pytest
import yaml

from propagate_app.cli import main


@pytest.fixture()
def valid_config(tmp_path):
    config = {
        "version": "6",
        "agent": {"command": "echo {prompt_file}"},
        "repositories": {"test-repo": {"url": "git@github.com:test/test.git"}},
        "executions": {
            "hello": {
                "repository": "test-repo",
                "sub_tasks": [{"id": "greet", "prompt": "say hi"}],
            },
        },
    }
    path = tmp_path / "propagate.yaml"
    path.write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")
    return path


def test_validate_valid_config(valid_config):
    result = main(["validate", "--config", str(valid_config)])
    assert result == 0


def test_validate_missing_config(tmp_path):
    result = main(["validate", "--config", str(tmp_path / "nope.yaml")])
    assert result == 1


def test_validate_invalid_config(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("version: '6'\n", encoding="utf-8")
    result = main(["validate", "--config", str(path)])
    assert result == 1
