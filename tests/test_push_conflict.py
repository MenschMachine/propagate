from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "propagate.py"
CLI_PYTHON = REPO_ROOT / "venv" / "bin" / "python"
if not CLI_PYTHON.exists():
    CLI_PYTHON = Path(sys.executable)


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def _build_python_command(script_path: Path, *args: str) -> str:
    parts = [shlex.quote(str(CLI_PYTHON)), shlex.quote(str(script_path))]
    parts.extend(shlex.quote(arg) for arg in args)
    return " ".join(parts)


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI_PYTHON), str(CLI_PATH), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )


@pytest.fixture()
def ctx(tmp_path: Path):
    workspace = tmp_path
    repo = workspace / "repo"
    repo.mkdir()
    remote_repo = workspace / "remote.git"
    second_clone = workspace / "second"
    target_file = repo / "artifact.txt"
    prompt_path = repo / "config" / "prompts" / "task.md"
    config_path = repo / "config" / "propagate.yaml"

    mutate_script = repo / "mutate_repo.py"
    mutate_script.write_text(
        "from __future__ import annotations\nimport sys\nfrom pathlib import Path\n"
        "prompt_path = Path(sys.argv[1])\ntarget_path = Path(sys.argv[2])\ncontent = sys.argv[3]\n"
        "if not prompt_path.exists():\n    raise SystemExit('prompt file missing during agent run')\n"
        "target_path.write_text(content, encoding='utf-8')\n",
        encoding="utf-8",
    )
    emit_script = repo / "emit_text.py"
    emit_script.write_text("import sys\nsys.stdout.write(sys.argv[1])\n", encoding="utf-8")

    _run_git("init", "-b", "main", cwd=repo)
    _run_git("config", "user.name", "Propagate Tests", cwd=repo)
    _run_git("config", "user.email", "propagate@example.com", cwd=repo)
    subprocess.run(["git", "init", "--bare", str(remote_repo)], cwd=workspace, check=True, capture_output=True)
    _run_git("remote", "add", "origin", str(remote_repo), cwd=repo)

    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("Task prompt.\n", encoding="utf-8")
    target_file.write_text("initial content\n", encoding="utf-8")

    config_data: dict[str, object] = {
        "version": "6",
        "agent": {"command": _build_python_command(mutate_script, "{prompt_file}", str(target_file), "updated from agent\n")},
        "repositories": {"repo": {"path": str(repo)}},
        "context_sources": {
            "commit-message": {"command": _build_python_command(emit_script, "rebase test commit\n\nBody")},
        },
        "executions": {
            "default": {
                "repository": "repo",
                "git": {
                    "branch": {"name": "propagate/conflict-test", "base": "main", "reuse": True},
                    "commit": {"message_source": "commit-message"},
                    "push": {"remote": "origin"},
                },
                "before": ["git:branch"],
                "after": ["git:commit", "git:push"],
                "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
            }
        },
    }
    config_path.write_text(yaml.dump(config_data, sort_keys=False), encoding="utf-8")

    _run_git("add", "-A", cwd=repo)
    _run_git("commit", "-m", "initial commit", cwd=repo)
    _run_git("push", "--set-upstream", "origin", "main", cwd=repo)

    return SimpleNamespace(
        repo=repo,
        remote_repo=remote_repo,
        second_clone=second_clone,
        target_file=target_file,
        config_path=config_path,
    )


def _push_ahead_commit(ctx: SimpleNamespace, *, file_path: str, content: str) -> None:
    """Clone the remote, create propagate/conflict-test, commit a change, push."""
    subprocess.run(["git", "clone", str(ctx.remote_repo), str(ctx.second_clone)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Second Clone"], cwd=ctx.second_clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "second@example.com"], cwd=ctx.second_clone, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "propagate/conflict-test"], cwd=ctx.second_clone, check=True, capture_output=True)
    (ctx.second_clone / file_path).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=ctx.second_clone, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "remote commit ahead of local"], cwd=ctx.second_clone, check=True, capture_output=True)
    subprocess.run(["git", "push", "--set-upstream", "origin", "propagate/conflict-test"], cwd=ctx.second_clone, check=True, capture_output=True)


def test_push_conflict_rebases_and_retries(ctx: SimpleNamespace) -> None:
    _push_ahead_commit(ctx, file_path="remote_file.txt", content="from remote\n")

    result = _run_cli("run", "--config", str(ctx.config_path), cwd=ctx.repo)

    assert result.returncode == 0, result.stderr

    # initial + remote's commit + local's rebased commit
    log = subprocess.run(
        ["git", "log", "--oneline", "propagate/conflict-test"],
        cwd=ctx.repo, text=True, capture_output=True, check=True,
    )
    assert len([line for line in log.stdout.strip().splitlines() if line]) == 3

    remote_log = subprocess.run(
        ["git", "log", "--oneline", "refs/heads/propagate/conflict-test"],
        cwd=ctx.remote_repo, text=True, capture_output=True, check=True,
    )
    assert len([line for line in remote_log.stdout.strip().splitlines() if line]) == 3

    # Remote branch contains the agent's content
    remote_content = subprocess.run(
        ["git", "show", "refs/heads/propagate/conflict-test:artifact.txt"],
        cwd=ctx.remote_repo, text=True, capture_output=True, check=True,
    )
    assert remote_content.stdout == "updated from agent\n"


def test_push_conflict_rebase_fails_on_merge_conflict(ctx: SimpleNamespace) -> None:
    _push_ahead_commit(ctx, file_path="artifact.txt", content="conflicting remote content\n")

    result = _run_cli("run", "--config", str(ctx.config_path), cwd=ctx.repo)

    assert result.returncode == 1
    assert "failed" in result.stderr.lower()
    assert "conflict" in result.stderr.lower()

    # Working tree is clean — rebase was aborted (ignore untracked context store files)
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ctx.repo, text=True, capture_output=True, check=True,
    )
    non_context_lines = [
        line for line in status.stdout.strip().splitlines()
        if ".propagate-context/" not in line
    ]
    assert non_context_lines == []

    assert not (ctx.repo / ".git" / "rebase-merge").exists()
    assert not (ctx.repo / ".git" / "rebase-apply").exists()
