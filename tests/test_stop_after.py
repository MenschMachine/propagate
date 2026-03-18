from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "propagate.py"
CLI_PYTHON = REPO_ROOT / "venv" / "bin" / "python"
if not CLI_PYTHON.exists():
    CLI_PYTHON = Path(sys.executable)


@pytest.fixture()
def workspace(tmp_path):
    config_dir = tmp_path / "config"
    prompt_dir = config_dir / "prompts"
    prompt_dir.mkdir(parents=True)

    invocation_log = tmp_path / "invocations.json"
    capture_script = tmp_path / "capture_invocation.py"
    capture_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "import json",
                "import os",
                "import sys",
                "from pathlib import Path",
                "",
                "prompt_path = Path(sys.argv[1])",
                "log_path = Path(sys.argv[2])",
                "items = []",
                "if log_path.exists():",
                "    items = json.loads(log_path.read_text(encoding='utf-8'))",
                "items.append({",
                "    'cwd': os.getcwd(),",
                "    'prompt': prompt_path.read_text(encoding='utf-8'),",
                "    'files': sorted(os.listdir('.')),",
                "})",
                "log_path.write_text(json.dumps(items), encoding='utf-8')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    agent_command = " ".join(
        [
            shlex.quote(str(CLI_PYTHON)),
            shlex.quote(str(capture_script)),
            "{prompt_file}",
            shlex.quote(str(invocation_log)),
        ]
    )

    return {
        "tmp_path": tmp_path,
        "config_dir": config_dir,
        "prompt_dir": prompt_dir,
        "invocation_log": invocation_log,
        "agent_command": agent_command,
    }


def write_config(config_dir, data):
    config_path = config_dir / "propagate.yaml"
    config_path.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
    return config_path


def run_cli(*args, cwd):
    return subprocess.run(
        [str(CLI_PYTHON), str(CLI_PATH), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _build_abc_config(workspace):
    """Build a three-execution DAG: a → b → c via propagation triggers."""
    ws = workspace
    repo_dir = ws["tmp_path"] / "repo"
    repo_dir.mkdir()

    for name in ("a", "b", "c"):
        (ws["prompt_dir"] / f"{name}.md").write_text(f"task {name}\n", encoding="utf-8")

    return write_config(
        ws["config_dir"],
        {
            "version": "6",
            "agent": {"command": ws["agent_command"]},
            "repositories": {"repo": {"path": "../repo"}},
            "executions": {
                "a": {
                    "repository": "repo",
                    "sub_tasks": [{"id": "a", "prompt": "./prompts/a.md"}],
                },
                "b": {
                    "repository": "repo",
                    "sub_tasks": [{"id": "b", "prompt": "./prompts/b.md"}],
                },
                "c": {
                    "repository": "repo",
                    "sub_tasks": [{"id": "c", "prompt": "./prompts/c.md"}],
                },
            },
            "propagation": {
                "triggers": [
                    {"after": "a", "run": "b"},
                    {"after": "b", "run": "c"},
                ],
            },
        },
    )


def test_stop_after_halts_after_named_execution(workspace):
    config_path = _build_abc_config(workspace)

    result = run_cli(
        "run", "--config", str(config_path), "--execution", "a", "--stop-after", "b",
        cwd=workspace["tmp_path"],
    )

    assert result.returncode == 0, result.stderr
    invocations = json.loads(workspace["invocation_log"].read_text(encoding="utf-8"))
    executed_prompts = [inv["prompt"].strip() for inv in invocations]
    assert executed_prompts == ["task a", "task b"]


def test_stop_after_on_last_execution_completes_normally(workspace):
    config_path = _build_abc_config(workspace)

    result = run_cli(
        "run", "--config", str(config_path), "--execution", "a", "--stop-after", "c",
        cwd=workspace["tmp_path"],
    )

    assert result.returncode == 0, result.stderr
    invocations = json.loads(workspace["invocation_log"].read_text(encoding="utf-8"))
    executed_prompts = [inv["prompt"].strip() for inv in invocations]
    assert executed_prompts == ["task a", "task b", "task c"]


def test_without_stop_after_all_executions_run(workspace):
    config_path = _build_abc_config(workspace)

    result = run_cli(
        "run", "--config", str(config_path), "--execution", "a",
        cwd=workspace["tmp_path"],
    )

    assert result.returncode == 0, result.stderr
    invocations = json.loads(workspace["invocation_log"].read_text(encoding="utf-8"))
    executed_prompts = [inv["prompt"].strip() for inv in invocations]
    assert executed_prompts == ["task a", "task b", "task c"]


def test_stop_after_preserves_state_for_resume(workspace):
    config_path = _build_abc_config(workspace)

    result = run_cli(
        "run", "--config", str(config_path), "--execution", "a", "--stop-after", "b",
        cwd=workspace["tmp_path"],
    )
    assert result.returncode == 0, result.stderr

    # State file should exist so --resume can pick up from here
    from propagate_app.run_state import state_file_path
    assert state_file_path(config_path).exists()

    # Resume should run c (the remaining execution)
    result2 = run_cli(
        "run", "--config", str(config_path), "--resume",
        cwd=workspace["tmp_path"],
    )
    assert result2.returncode == 0, result2.stderr
    invocations = json.loads(workspace["invocation_log"].read_text(encoding="utf-8"))
    executed_prompts = [inv["prompt"].strip() for inv in invocations]
    assert executed_prompts == ["task a", "task b", "task c"]


def test_stop_after_unreachable_target_warns(workspace):
    config_path = _build_abc_config(workspace)

    result = run_cli(
        "run", "--config", str(config_path), "--execution", "c", "--stop-after", "a",
        cwd=workspace["tmp_path"],
    )

    assert result.returncode == 0, result.stderr
    assert "not reachable" in result.stderr


def test_stop_after_unknown_execution_fails(workspace):
    config_path = _build_abc_config(workspace)

    result = run_cli(
        "run", "--config", str(config_path), "--execution", "a", "--stop-after", "nonexistent",
        cwd=workspace["tmp_path"],
    )

    assert result.returncode == 1
    assert "not found in config" in result.stderr
