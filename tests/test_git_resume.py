"""Tests for resume with git state and execution context preservation."""
from __future__ import annotations

import json
import os
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


def _run_cli(*args: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI_PYTHON), str(CLI_PATH), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env or os.environ.copy(),
    )


def _q(path: Path) -> str:
    return shlex.quote(str(path))


@pytest.fixture()
def resume_ctx(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    remote_repo = tmp_path / "remote.git"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    prompt_path = config_dir / "prompts" / "task.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("Task prompt.\n", encoding="utf-8")

    config_path = config_dir / "propagate.yaml"

    # Emit script for context source
    emit_script = scripts_dir / "emit_text.py"
    emit_script.write_text("import sys\nsys.stdout.write(sys.argv[1])\n", encoding="utf-8")

    # Init repo
    _run_git("init", "-b", "main", cwd=repo)
    _run_git("config", "user.name", "Propagate Tests", cwd=repo)
    _run_git("config", "user.email", "propagate@example.com", cwd=repo)
    subprocess.run(["git", "init", "--bare", str(remote_repo)], cwd=tmp_path, check=True, capture_output=True)
    _run_git("remote", "add", "origin", str(remote_repo), cwd=repo)

    initial_file = repo / "initial.txt"
    initial_file.write_text("initial\n", encoding="utf-8")
    _run_git("add", "-A", cwd=repo)
    _run_git("commit", "-m", "initial commit", cwd=repo)
    _run_git("push", "--set-upstream", "origin", "main", cwd=repo)

    return SimpleNamespace(
        repo=repo,
        remote_repo=remote_repo,
        config_path=config_path,
        prompt_path=prompt_path,
        emit_script=emit_script,
        scripts_dir=scripts_dir,
        config_dir=config_dir,
    )


def _write_config(ctx: SimpleNamespace, config_data: dict) -> None:
    ctx.config_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.config_path.write_text(yaml.dump(config_data, sort_keys=False), encoding="utf-8")


def _emit_cmd(ctx: SimpleNamespace, text: str) -> str:
    return f"{_q(CLI_PYTHON)} {_q(ctx.emit_script)} {shlex.quote(text)}"


@pytest.mark.slow
def test_resume_preserves_git_state_and_context(resume_ctx: SimpleNamespace) -> None:
    """First run: task1 succeeds (git:branch + context:set), task2 fails.
    Resume: git state restored from repo, context preserved, task2 succeeds, git:push works.
    """
    ctx = resume_ctx
    target_file = ctx.repo / "artifact.txt"
    fail_flag = ctx.scripts_dir / "fail_flag.txt"

    # Dispatcher: task1 writes a file, task2 fails first time then succeeds.
    dispatcher = ctx.scripts_dir / "dispatcher.py"
    dispatcher.write_text(
        "import subprocess, sys\n"
        "from pathlib import Path\n"
        "prompt = Path(sys.argv[1]).read_text()\n"
        "if 'TASK1' in prompt:\n"
        f"    target = {repr(str(target_file))}\n"
        f"    Path(target).write_text('updated\\n', encoding='utf-8')\n"
        "elif 'TASK2' in prompt:\n"
        f"    flag = Path({repr(str(fail_flag))})\n"
        "    if not flag.exists():\n"
        "        flag.write_text('failed-once', encoding='utf-8')\n"
        "        sys.exit(1)\n"
        f"    Path({repr(str(target_file))}).write_text('task2-done\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )

    # Prompt files
    prompt1 = ctx.config_dir / "prompts" / "task1.md"
    prompt2 = ctx.config_dir / "prompts" / "task2.md"
    prompt1.write_text("TASK1: do something\n", encoding="utf-8")
    prompt2.write_text("TASK2: do another thing\n", encoding="utf-8")

    agent_cmd = f"{_q(CLI_PYTHON)} {_q(dispatcher)} {{prompt_file}}"

    _write_config(ctx, {
        "version": "6",
        "agent": {"command": agent_cmd},
        "repositories": {"repo": {"path": str(ctx.repo)}},
        "context_sources": {"commit-msg": {"command": _emit_cmd(ctx, "feat: resume test\n")}},
        "executions": {
            "default": {
                "repository": "repo",
                "git": {
                    "branch": {"name": "feat/resume-test", "base": "main"},
                    "commit": {"message_source": "commit-msg"},
                    "push": {"remote": "origin"},
                },
                "before": ["git:branch"],
                "sub_tasks": [
                    {
                        "id": "task1",
                        "prompt": "./prompts/task1.md",
                        "after": ["git:commit"],
                    },
                    {
                        "id": "task2",
                        "prompt": "./prompts/task2.md",
                        "after": ["git:commit"],
                    },
                ],
                "after": ["git:push"],
            },
        },
    })

    # First run: task1 succeeds, task2 fails
    result1 = _run_cli("run", "--config", str(ctx.config_path), cwd=ctx.repo)
    assert result1.returncode == 1, f"Expected failure on first run.\nstdout: {result1.stdout}\nstderr: {result1.stderr}"

    # Verify we're on the feature branch (git:branch ran)
    branch_result = _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=ctx.repo)
    assert branch_result.stdout.strip() == "feat/resume-test"

    # Verify state file exists for resume
    state_files = list(ctx.config_dir.glob(".propagate-state-*.yaml"))
    assert state_files, "Run state file should exist after partial failure"

    # Resume: task2 should succeed now (flag file exists), git:push should work
    result2 = _run_cli("run", "--config", str(ctx.config_path), "--resume", cwd=ctx.repo)
    assert result2.returncode == 0, f"Resume should succeed.\nstdout: {result2.stdout}\nstderr: {result2.stderr}"

    # Verify push succeeded — branch exists on remote
    remote_branches = subprocess.run(
        ["git", "branch", "-r"],
        cwd=ctx.repo, text=True, capture_output=True, check=True,
    )
    assert "origin/feat/resume-test" in remote_branches.stdout


@pytest.mark.slow
def test_resume_preserves_execution_context_keys(resume_ctx: SimpleNamespace) -> None:
    """Context keys written by task1's after hook survive into a resumed task2 run."""
    ctx = resume_ctx
    fail_flag = ctx.scripts_dir / "fail_flag2.txt"
    result_file = ctx.scripts_dir / "context_read_result.txt"
    context_root = ctx.config_dir / ".propagate-context-propagate"

    # Dispatcher: task1 writes a context key via the context store directory directly,
    # task2 fails on first attempt, succeeds on second, and reads the context key.
    dispatcher = ctx.scripts_dir / "dispatcher2.py"
    dispatcher.write_text(
        "import sys, os\nfrom pathlib import Path\n"
        "prompt = Path(sys.argv[1]).read_text()\n"
        "if 'TASK1' in prompt:\n"
        "    # Write context key directly to execution context dir\n"
        f"    ctx_dir = Path({repr(str(context_root))}) / os.environ.get('PROPAGATE_EXECUTION', 'default')\n"
        "    ctx_dir.mkdir(parents=True, exist_ok=True)\n"
        "    (ctx_dir / 'my-key').write_text('my-value', encoding='utf-8')\n"
        "elif 'TASK2' in prompt:\n"
        f"    flag = Path({repr(str(fail_flag))})\n"
        "    if not flag.exists():\n"
        "        flag.write_text('failed', encoding='utf-8')\n"
        "        sys.exit(1)\n"
        "    # On resume: verify context key from task1 is still available\n"
        f"    ctx_dir = Path({repr(str(context_root))}) / os.environ.get('PROPAGATE_EXECUTION', 'default')\n"
        "    value = (ctx_dir / 'my-key').read_text(encoding='utf-8')\n"
        f"    Path({repr(str(result_file))}).write_text(value, encoding='utf-8')\n",
        encoding="utf-8",
    )

    prompt1 = ctx.config_dir / "prompts" / "task1.md"
    prompt2 = ctx.config_dir / "prompts" / "task2.md"
    prompt1.write_text("TASK1\n", encoding="utf-8")
    prompt2.write_text("TASK2\n", encoding="utf-8")

    agent_cmd = f"{_q(CLI_PYTHON)} {_q(dispatcher)} {{prompt_file}}"

    _write_config(ctx, {
        "version": "6",
        "agent": {"command": agent_cmd},
        "repositories": {"repo": {"path": str(ctx.repo)}},
        "executions": {
            "default": {
                "repository": "repo",
                "sub_tasks": [
                    {"id": "task1", "prompt": "./prompts/task1.md"},
                    {"id": "task2", "prompt": "./prompts/task2.md"},
                ],
            },
        },
    })

    # First run: task1 succeeds (writes context key), task2 fails
    result1 = _run_cli("run", "--config", str(ctx.config_path), cwd=ctx.repo)
    assert result1.returncode == 1, f"Expected failure.\nstdout: {result1.stdout}\nstderr: {result1.stderr}"

    # Verify context key was written by task1
    assert (context_root / "default" / "my-key").exists(), "Context key should exist after task1"

    # Resume: task2 should succeed and read the preserved context key
    result2 = _run_cli("run", "--config", str(ctx.config_path), "--resume", cwd=ctx.repo)
    assert result2.returncode == 0, f"Resume should succeed.\nstdout: {result2.stdout}\nstderr: {result2.stderr}"

    # Verify context was preserved — task2 read the key and wrote it to result_file
    assert result_file.exists(), "Task2 should have read the context key and written result"
    assert result_file.read_text(encoding="utf-8") == "my-value"


@pytest.mark.slow
def test_resume_preserves_commit_message_for_pr(resume_ctx: SimpleNamespace) -> None:
    """git:pr on resume uses the commit message persisted by git:commit in the first run."""
    ctx = resume_ctx
    target_file = ctx.repo / "artifact.txt"
    fail_flag = ctx.scripts_dir / "fail_flag3.txt"

    # Fake gh that logs its invocation
    bin_dir = ctx.scripts_dir / "bin"
    bin_dir.mkdir()
    gh_log = ctx.scripts_dir / "gh-log.json"

    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "body = ''\n"
        "if '--body-file' in args:\n"
        "    body = Path(args[args.index('--body-file') + 1]).read_text()\n"
        "Path(os.environ['GH_LOG']).write_text(json.dumps({'args': args, 'body': body}))\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    # Dispatcher: task1 writes a file, task2 fails first time then succeeds.
    dispatcher = ctx.scripts_dir / "dispatcher3.py"
    dispatcher.write_text(
        "import subprocess, sys\n"
        "from pathlib import Path\n"
        "prompt = Path(sys.argv[1]).read_text()\n"
        "if 'TASK1' in prompt:\n"
        f"    Path({repr(str(target_file))}).write_text('updated\\n', encoding='utf-8')\n"
        "elif 'TASK2' in prompt:\n"
        f"    flag = Path({repr(str(fail_flag))})\n"
        "    if not flag.exists():\n"
        "        flag.write_text('failed-once', encoding='utf-8')\n"
        "        sys.exit(1)\n",
        encoding="utf-8",
    )

    prompt1 = ctx.config_dir / "prompts" / "task1.md"
    prompt2 = ctx.config_dir / "prompts" / "task2.md"
    prompt1.write_text("TASK1: do something\n", encoding="utf-8")
    prompt2.write_text("TASK2: do another thing\n", encoding="utf-8")

    agent_cmd = f"{_q(CLI_PYTHON)} {_q(dispatcher)} {{prompt_file}}"

    _write_config(ctx, {
        "version": "6",
        "agent": {"command": agent_cmd},
        "repositories": {"repo": {"path": str(ctx.repo)}},
        "context_sources": {"commit-msg": {"command": _emit_cmd(ctx, "feat: pr resume test\n\nPR body content")}},
        "executions": {
            "default": {
                "repository": "repo",
                "git": {
                    "branch": {"name": "feat/pr-resume", "base": "main"},
                    "commit": {"message_source": "commit-msg"},
                    "push": {"remote": "origin"},
                    "pr": {"base": "main"},
                },
                "before": ["git:branch"],
                "sub_tasks": [
                    {
                        "id": "task1",
                        "prompt": "./prompts/task1.md",
                        "after": ["git:commit"],
                    },
                    {
                        "id": "task2",
                        "prompt": "./prompts/task2.md",
                    },
                ],
                "after": ["git:push", "git:pr"],
            },
        },
    })

    # First run: task1 succeeds (git:branch + git:commit run), task2 fails
    result1 = _run_cli("run", "--config", str(ctx.config_path), cwd=ctx.repo)
    assert result1.returncode == 1, f"Expected failure on first run.\nstdout: {result1.stdout}\nstderr: {result1.stderr}"

    # Resume with fake gh on PATH
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["GH_LOG"] = str(gh_log)
    result2 = subprocess.run(
        [str(CLI_PYTHON), str(CLI_PATH), "run", "--config", str(ctx.config_path), "--resume"],
        cwd=ctx.repo, text=True, capture_output=True, check=False, env=env,
    )
    assert result2.returncode == 0, f"Resume should succeed.\nstdout: {result2.stdout}\nstderr: {result2.stderr}"
    assert "empty" not in result2.stderr.lower(), f"Should not get empty commit message error.\nstderr: {result2.stderr}"

    # Verify fake gh was invoked with correct commit message as PR title
    assert gh_log.exists(), "fake gh should have been invoked"
    invocation = json.loads(gh_log.read_text())
    assert invocation["args"][:2] == ["pr", "create"]
    assert invocation["args"][invocation["args"].index("--title") + 1] == "feat: pr resume test"
    assert "PR body content" in invocation["body"]
