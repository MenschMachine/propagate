from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from conftest import inject_test_repository

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "propagate.py"
CLI_PYTHON = REPO_ROOT / "venv" / "bin" / "python"
if not CLI_PYTHON.exists():
    CLI_PYTHON = Path(sys.executable)


def _build_python_command(script_path: Path, *args: str) -> str:
    parts = [shlex.quote(str(CLI_PYTHON)), shlex.quote(str(script_path))]
    parts.extend(shlex.quote(arg) for arg in args)
    return " ".join(parts)


def _write_config(workspace: Path, config_data: dict, config_dir: Path | None = None) -> Path:
    config_root = config_dir or (workspace / "config")
    prompt_dir = config_root / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_root / "propagate.yaml"
    if "repositories" not in config_data:
        executions = config_data.get("executions")
        if isinstance(executions, dict):
            repositories, patched_executions = inject_test_repository(executions, workspace)
            config_data = {**config_data, "repositories": repositories, "executions": patched_executions}
    config_path.write_text(yaml.dump(config_data, sort_keys=False), encoding="utf-8")
    return config_path


def _run_cli(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI_PYTHON), str(CLI_PATH), *args],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )


def _make_invocation_script(workspace: Path) -> tuple[Path, Path]:
    """Create a script that appends each prompt to a JSON log file. Returns (script, log)."""
    script = workspace / "append_prompt.py"
    log = workspace / "invocations.json"
    script.write_text(
        "\n".join([
            "from __future__ import annotations",
            "",
            "import json",
            "import sys",
            "from pathlib import Path",
            "",
            "prompt_path = Path(sys.argv[1])",
            "log_path = Path(sys.argv[2])",
            "items = []",
            "if log_path.exists():",
            "    items = json.loads(log_path.read_text(encoding='utf-8'))",
            "items.append(prompt_path.read_text(encoding='utf-8'))",
            "log_path.write_text(json.dumps(items), encoding='utf-8')",
        ])
        + "\n",
        encoding="utf-8",
    )
    return script, log


def test_skip_execution(tmp_path):
    """Skipped execution is never run; downstream stays pending."""
    workspace = tmp_path
    script, log = _make_invocation_script(workspace)
    config_dir = workspace / "config"
    prompt_dir = config_dir / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "build.md").write_text("build prompt\n", encoding="utf-8")
    (prompt_dir / "test.md").write_text("test prompt\n", encoding="utf-8")

    config_path = _write_config(
        workspace,
        {
            "version": "6",
            "agent": {
                "command": _build_python_command(script, "{prompt_file}", str(log)),
            },
            "executions": {
                "build": {
                    "sub_tasks": [{"id": "build", "prompt": "./prompts/build.md"}],
                },
                "test": {
                    "depends_on": ["build"],
                    "sub_tasks": [{"id": "test", "prompt": "./prompts/test.md"}],
                },
            },
        },
        config_dir,
    )

    result = _run_cli(workspace, "run", "--config", str(config_path), "--execution", "build", "--skip", "build")
    assert result.returncode == 0, result.stderr
    # Neither build nor test should have run (test depends on skipped build)
    assert not log.exists()


def test_skip_task_within_execution(tmp_path):
    """Skipped task is not run but other tasks in the execution proceed."""
    workspace = tmp_path
    script, log = _make_invocation_script(workspace)
    config_dir = workspace / "config"
    prompt_dir = config_dir / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "lint.md").write_text("lint prompt\n", encoding="utf-8")
    (prompt_dir / "test.md").write_text("test prompt\n", encoding="utf-8")

    config_path = _write_config(
        workspace,
        {
            "version": "6",
            "agent": {
                "command": _build_python_command(script, "{prompt_file}", str(log)),
            },
            "executions": {
                "build": {
                    "sub_tasks": [
                        {"id": "lint", "prompt": "./prompts/lint.md"},
                        {"id": "test", "prompt": "./prompts/test.md"},
                    ],
                },
            },
        },
        config_dir,
    )

    result = _run_cli(workspace, "run", "--config", str(config_path), "--skip", "build/lint")
    assert result.returncode == 0, result.stderr
    invocations = json.loads(log.read_text(encoding="utf-8"))
    # Only 'test' ran, 'lint' was skipped
    assert len(invocations) == 1
    assert "test prompt" in invocations[0]


def test_skip_unknown_execution_fails(tmp_path):
    """Referencing a nonexistent execution in --skip is an error."""
    workspace = tmp_path
    script, log = _make_invocation_script(workspace)
    config_dir = workspace / "config"
    prompt_dir = config_dir / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "task.md").write_text("task\n", encoding="utf-8")

    config_path = _write_config(
        workspace,
        {
            "version": "6",
            "agent": {
                "command": _build_python_command(script, "{prompt_file}", str(log)),
            },
            "executions": {
                "build": {
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                },
            },
        },
        config_dir,
    )

    result = _run_cli(workspace, "run", "--config", str(config_path), "--skip", "nonexistent")
    assert result.returncode == 1
    assert "nonexistent" in result.stderr
    assert not log.exists()


def test_skip_unknown_task_fails(tmp_path):
    """Referencing a nonexistent task in --skip is an error."""
    workspace = tmp_path
    script, log = _make_invocation_script(workspace)
    config_dir = workspace / "config"
    prompt_dir = config_dir / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "task.md").write_text("task\n", encoding="utf-8")

    config_path = _write_config(
        workspace,
        {
            "version": "6",
            "agent": {
                "command": _build_python_command(script, "{prompt_file}", str(log)),
            },
            "executions": {
                "build": {
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                },
            },
        },
        config_dir,
    )

    result = _run_cli(workspace, "run", "--config", str(config_path), "--skip", "build/nonexistent")
    assert result.returncode == 1
    assert "nonexistent" in result.stderr
    assert not log.exists()


def test_skip_all_executions_succeeds(tmp_path):
    """Skipping every execution results in a clean exit."""
    workspace = tmp_path
    script, log = _make_invocation_script(workspace)
    config_dir = workspace / "config"
    prompt_dir = config_dir / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "task.md").write_text("task\n", encoding="utf-8")

    config_path = _write_config(
        workspace,
        {
            "version": "6",
            "agent": {
                "command": _build_python_command(script, "{prompt_file}", str(log)),
            },
            "executions": {
                "build": {
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                },
            },
        },
        config_dir,
    )

    result = _run_cli(workspace, "run", "--config", str(config_path), "--skip", "build")
    assert result.returncode == 0, result.stderr
    assert not log.exists()


def test_skip_multiple(tmp_path):
    """Multiple --skip flags: skip execution + skip task in another."""
    workspace = tmp_path
    script, log = _make_invocation_script(workspace)
    config_dir = workspace / "config"
    prompt_dir = config_dir / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "lint.md").write_text("lint prompt\n", encoding="utf-8")
    (prompt_dir / "test.md").write_text("test prompt\n", encoding="utf-8")
    (prompt_dir / "deploy.md").write_text("deploy prompt\n", encoding="utf-8")

    config_path = _write_config(
        workspace,
        {
            "version": "6",
            "agent": {
                "command": _build_python_command(script, "{prompt_file}", str(log)),
            },
            "executions": {
                "build": {
                    "sub_tasks": [
                        {"id": "lint", "prompt": "./prompts/lint.md"},
                        {"id": "test", "prompt": "./prompts/test.md"},
                    ],
                },
                "deploy": {
                    "depends_on": ["build"],
                    "sub_tasks": [{"id": "deploy", "prompt": "./prompts/deploy.md"}],
                },
            },
        },
        config_dir,
    )

    result = _run_cli(workspace, "run", "--config", str(config_path), "--execution", "build", "--skip", "build/lint", "--skip", "deploy")
    assert result.returncode == 0, result.stderr
    # lint skipped, test ran, deploy skipped
    invocations = json.loads(log.read_text(encoding="utf-8"))
    assert len(invocations) == 1
    assert "test prompt" in invocations[0]


def test_skip_execution_downstream_propagation_blocked(tmp_path):
    """Propagation trigger from a skipped execution never fires."""
    workspace = tmp_path
    script, log = _make_invocation_script(workspace)
    config_dir = workspace / "config"
    prompt_dir = config_dir / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "build.md").write_text("build prompt\n", encoding="utf-8")
    (prompt_dir / "deploy.md").write_text("deploy prompt\n", encoding="utf-8")

    config_path = _write_config(
        workspace,
        {
            "version": "6",
            "agent": {
                "command": _build_python_command(script, "{prompt_file}", str(log)),
            },
            "executions": {
                "build": {
                    "sub_tasks": [{"id": "build", "prompt": "./prompts/build.md"}],
                },
                "deploy": {
                    "sub_tasks": [{"id": "deploy", "prompt": "./prompts/deploy.md"}],
                },
            },
            "propagation": {
                "triggers": [
                    {"after": "build", "run": "deploy"},
                ],
            },
        },
        config_dir,
    )

    result = _run_cli(workspace, "run", "--config", str(config_path), "--execution", "build", "--skip", "build")
    assert result.returncode == 0, result.stderr
    # build skipped, deploy never triggered
    assert not log.exists()
