import pytest
import yaml

from propagate_app.cli import main


@pytest.fixture()
def valid_config(tmp_path):
    config = {
        "version": "6",
        "agent": {"command": "echo {prompt_file}"},
        "repositories": {"test-repo": {"url": "git@github.com:test/test.git"}},
        "signals": {
            "task.complete": {"payload": {"result": {"type": "string"}}},
        },
        "executions": {
            "pull-data": {
                "repository": "test-repo",
                "sub_tasks": [{"id": "pull", "prompt": "pull data"}],
            },
            "process-data": {
                "repository": "test-repo",
                "depends_on": ["pull-data"],
                "sub_tasks": [
                    {"id": "setup", "prompt": "setup"},
                    {"id": "process", "prompt": "process data", "when": "!:retry", "goto": "setup"},
                    {"id": "wait", "wait_for_signal": "task.complete", "routes": [
                        {"when": {"result": "retry"}, "goto": "setup"},
                        {"when": {"result": "ok"}, "continue": True},
                    ]},
                    {"id": "finalize", "prompt": "finalize", "when": ":flag"},
                ],
            },
            "evaluate": {
                "repository": "test-repo",
                "depends_on": ["process-data"],
                "sub_tasks": [{"id": "eval", "prompt": "evaluate"}],
            },
        },
        "propagation": {
            "triggers": [
                {"after": "pull-data", "run": "process-data"},
                {"after": "process-data", "run": "evaluate"},
            ],
        },
    }
    path = tmp_path / "propagate.yaml"
    path.write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")
    return path


def test_visualize_valid_config(valid_config, capsys):
    result = main(["visualize", "--config", str(valid_config)])
    assert result == 0
    captured = capsys.readouterr()
    assert "Execution Flow:" in captured.out
    assert "pull-data" in captured.out
    assert "process-data" in captured.out
    assert "evaluate" in captured.out
    assert "-> depends on:" in captured.out
    assert "-> triggers:" in captured.out


def test_visualize_missing_config(tmp_path):
    result = main(["visualize", "--config", str(tmp_path / "nope.yaml")])
    assert result == 1
