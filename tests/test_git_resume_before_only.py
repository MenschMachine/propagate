"""Test: resume after before-hooks completed but sub-task failed before completion.

Reproduces the bug where:
1. Before hooks run (git:branch persists state to context).
2. Sub-task fails before on_phase_completed fires for it.
3. State saved: completed_execution_phases has 'before', completed_tasks is empty.
4. On resume: context was cleared (completed_tasks empty), before hooks skipped
   (completed_execution_phase == 'before'), git:push fails because selected_branch is None.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "propagate.py"
CLI_PYTHON = REPO_ROOT / "venv" / "bin" / "python"
if not CLI_PYTHON.exists():
    CLI_PYTHON = Path(sys.executable)


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI_PYTHON), str(CLI_PATH), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _q(path: Path) -> str:
    return shlex.quote(str(path))


@pytest.fixture()
def ctx(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    remote_repo = tmp_path / "remote.git"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    prompt_path = config_dir / "prompts" / "task.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("Do the task.\n", encoding="utf-8")

    emit_script = scripts_dir / "emit_text.py"
    emit_script.write_text("import sys\nsys.stdout.write(sys.argv[1])\n", encoding="utf-8")

    config_path = config_dir / "propagate.yaml"

    _run_git("init", "-b", "main", cwd=repo)
    _run_git("config", "user.name", "Test", cwd=repo)
    _run_git("config", "user.email", "test@example.com", cwd=repo)
    subprocess.run(["git", "init", "--bare", str(remote_repo)], cwd=tmp_path, check=True, capture_output=True)
    _run_git("remote", "add", "origin", str(remote_repo), cwd=repo)
    (repo / "initial.txt").write_text("init\n", encoding="utf-8")
    _run_git("add", "-A", cwd=repo)
    _run_git("commit", "-m", "initial", cwd=repo)
    _run_git("push", "--set-upstream", "origin", "main", cwd=repo)

    return SimpleNamespace(
        repo=repo,
        config_path=config_path,
        prompt_path=prompt_path,
        emit_script=emit_script,
        scripts_dir=scripts_dir,
        config_dir=config_dir,
    )


def _emit_cmd(ctx: SimpleNamespace, text: str) -> str:
    return f"{_q(CLI_PYTHON)} {_q(ctx.emit_script)} {shlex.quote(text)}"


def test_resume_after_before_hooks_only(ctx: SimpleNamespace) -> None:
    """Before hooks complete, sub-task fails immediately. Resume must restore git state."""
    fail_flag = ctx.scripts_dir / "fail_flag.txt"

    dispatcher = ctx.scripts_dir / "dispatcher.py"
    dispatcher.write_text(
        "import sys\nfrom pathlib import Path\n"
        "prompt = Path(sys.argv[1]).read_text()\n"
        f"flag = Path({repr(str(fail_flag))})\n"
        "if not flag.exists():\n"
        "    flag.write_text('done', encoding='utf-8')\n"
        f"    Path({repr(str(ctx.repo / 'artifact.txt'))}).write_text('data\\n')\n"
        "    sys.exit(1)\n"
        f"Path({repr(str(ctx.repo / 'artifact.txt'))}).write_text('data\\n')\n",
        encoding="utf-8",
    )

    agent_cmd = f"{_q(CLI_PYTHON)} {_q(dispatcher)} {{prompt_file}}"

    config_data = {
        "version": "6",
        "agent": {"command": agent_cmd},
        "repositories": {"repo": {"path": str(ctx.repo)}},
        "context_sources": {"commit-msg": {"command": _emit_cmd(ctx, "feat: test commit")}},
        "executions": {
            "default": {
                "repository": "repo",
                "git": {
                    "branch": {"name": "feat/before-only-test", "base": "main"},
                    "commit": {"message_source": "commit-msg"},
                    "push": {"remote": "origin"},
                },
                "before": ["git:branch"],
                "sub_tasks": [{"id": "task1", "prompt": "./prompts/task.md"}],
                "after": ["git:commit", "git:push"],
            },
        },
    }
    ctx.config_path.write_text(yaml.dump(config_data, sort_keys=False), encoding="utf-8")

    # First run: git:branch succeeds, sub-task fails
    result1 = _run_cli("run", "--config", str(ctx.config_path), cwd=ctx.repo)
    assert result1.returncode == 1, f"Expected failure.\nstderr: {result1.stderr}"

    # Verify before hooks completed in state
    state_file = list(ctx.config_dir.glob(".propagate-state-*.yaml"))
    assert state_file, "State file must exist"
    state = yaml.safe_load(state_file[0].read_text(encoding="utf-8"))
    assert state.get("completed_execution_phases", {}).get("default") == "before"

    # Verify git state was persisted to context
    context_dir = ctx.config_dir / ".propagate-context" / "default"
    assert (context_dir / ":git.selected_branch").exists(), "git state must be persisted after git:branch"

    # Resume: before hooks skipped, sub-task succeeds, git:push must work
    result2 = _run_cli("run", "--config", str(ctx.config_path), "--resume", cwd=ctx.repo)
    assert result2.returncode == 0, f"Resume should succeed.\nstderr: {result2.stderr}"

    # Verify push succeeded
    remote_branches = _run_git("branch", "-r", cwd=ctx.repo)
    assert "origin/feat/before-only-test" in remote_branches.stdout
