from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from propagate_app.config_load import load_config
from propagate_app.errors import PropagateError

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
        env=os.environ.copy(),
    )


def _q(path: Path) -> str:
    return shlex.quote(str(path))


def _agent_cmd(script: Path, target: Path) -> str:
    """Agent that writes 'updated' to target, ignoring prompt_file."""
    return f"{_q(CLI_PYTHON)} {_q(script)} {{prompt_file}} {_q(target)}"


@pytest.fixture()
def git_ctx(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    remote_repo = tmp_path / "remote.git"
    # Config and scripts live OUTSIDE the repo so writing them doesn't dirty the working tree
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    target_file = repo / "artifact.txt"
    prompt_path = config_dir / "prompts" / "task.md"
    config_path = config_dir / "propagate.yaml"

    # Agent: writes fixed content to argv[2], accepts prompt_file as argv[1]
    mutate_script = scripts_dir / "mutate_repo.py"
    mutate_script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path(sys.argv[2]).write_text('updated\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )

    # Noop agent: just reads the prompt file to confirm it exists
    noop_script = scripts_dir / "noop_agent.py"
    noop_script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).read_text()  # just confirm prompt exists\n",
        encoding="utf-8",
    )

    # Failing agent
    fail_script = scripts_dir / "fail_agent.py"
    fail_script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")

    # Emit text to stdout (used as message_source)
    emit_script = scripts_dir / "emit_text.py"
    emit_script.write_text("import sys\nsys.stdout.write(sys.argv[1])\n", encoding="utf-8")

    # Write-marker script: writes content to argv[1]
    marker_script = scripts_dir / "write_marker.py"
    marker_script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text('ran\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )

    _run_git("init", "-b", "main", cwd=repo)
    _run_git("config", "user.name", "Propagate Tests", cwd=repo)
    _run_git("config", "user.email", "propagate@example.com", cwd=repo)
    subprocess.run(["git", "init", "--bare", str(remote_repo)], cwd=tmp_path, check=True, capture_output=True)
    _run_git("remote", "add", "origin", str(remote_repo), cwd=repo)

    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("Task prompt.\n", encoding="utf-8")
    target_file.write_text("initial\n", encoding="utf-8")

    _run_git("add", "-A", cwd=repo)
    _run_git("commit", "-m", "initial commit", cwd=repo)
    _run_git("push", "--set-upstream", "origin", "main", cwd=repo)

    return SimpleNamespace(
        repo=repo,
        remote_repo=remote_repo,
        target_file=target_file,
        config_path=config_path,
        prompt_path=prompt_path,
        mutate_script=mutate_script,
        noop_script=noop_script,
        fail_script=fail_script,
        emit_script=emit_script,
        marker_script=marker_script,
    )


def _write_config(ctx: SimpleNamespace, config_data: dict) -> None:
    ctx.config_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.config_path.write_text(yaml.dump(config_data, sort_keys=False), encoding="utf-8")


def _emit_cmd(ctx: SimpleNamespace, text: str) -> str:
    return f"{_q(CLI_PYTHON)} {_q(ctx.emit_script)} {shlex.quote(text)}"


# ---------------------------------------------------------------------------
# Parse-time tests
# ---------------------------------------------------------------------------


def test_unknown_git_command_raises_at_parse_time(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "propagate.yaml"
    (config_dir / "task.md").write_text("prompt\n")
    config_path.write_text(
        yaml.dump(
            {
                "version": "6",
                "agent": {"command": "echo {prompt_file}"},
                "repositories": {"repo": {"path": str(tmp_path)}},
                "executions": {
                    "my-exec": {
                        "repository": "repo",
                        "before": ["git:unknown"],
                        "sub_tasks": [{"id": "t1", "prompt": "task.md"}],
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(PropagateError, match="unknown git command 'git:unknown'"):
        load_config(config_path)


def test_known_git_commands_parse_ok(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "propagate.yaml"
    (config_dir / "task.md").write_text("prompt\n")
    config_path.write_text(
        yaml.dump(
            {
                "version": "6",
                "agent": {"command": "echo {prompt_file}"},
                "repositories": {"repo": {"path": str(tmp_path)}},
                "context_sources": {"commit-msg": {"command": "echo hi"}},
                "executions": {
                    "my-exec": {
                        "repository": "repo",
                        "git": {
                            "branch": {"name": "feat/test", "base": "main"},
                            "commit": {"message_source": "commit-msg"},
                            "push": {"remote": "origin"},
                        },
                        "before": ["git:branch"],
                        "after": ["git:push", "git:pr"],
                        "sub_tasks": [
                            {"id": "t1", "prompt": "task.md", "after": ["git:commit"]}
                        ],
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = load_config(config_path)
    exec_cfg = config.executions["my-exec"]
    assert exec_cfg.before == ["git:branch"]
    assert exec_cfg.after == ["git:push", "git:pr"]
    assert exec_cfg.sub_tasks[0].after == ["git:commit"]


# ---------------------------------------------------------------------------
# Integration: git:branch in execution before hook
# ---------------------------------------------------------------------------


def test_git_branch_in_before_hook_creates_branch(git_ctx: SimpleNamespace) -> None:
    _write_config(
        git_ctx,
        {
            "version": "6",
            "agent": {"command": _agent_cmd(git_ctx.mutate_script, git_ctx.target_file)},
            "repositories": {"repo": {"path": str(git_ctx.repo)}},
            "context_sources": {"commit-msg": {"command": _emit_cmd(git_ctx, "feat: hook branch\n")}},
            "executions": {
                "default": {
                    "repository": "repo",
                    "git": {
                        "branch": {"name": "feat/hook-branch", "base": "main"},
                        "commit": {"message_source": "commit-msg"},
                    },
                    "before": ["git:branch"],
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                }
            },
        },
    )
    result = _run_cli("run", "--config", str(git_ctx.config_path), cwd=git_ctx.repo)
    assert result.returncode == 0, result.stderr

    branch_out = subprocess.run(
        ["git", "branch", "--list", "feat/hook-branch"],
        cwd=git_ctx.repo, text=True, capture_output=True, check=True,
    )
    assert "feat/hook-branch" in branch_out.stdout


# ---------------------------------------------------------------------------
# Integration: git:commit in sub-task after hook
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_git_commit_in_subtask_after_hook_commits_changes(git_ctx: SimpleNamespace) -> None:
    _write_config(
        git_ctx,
        {
            "version": "6",
            "agent": {"command": _agent_cmd(git_ctx.mutate_script, git_ctx.target_file)},
            "repositories": {"repo": {"path": str(git_ctx.repo)}},
            "context_sources": {"commit-msg": {"command": _emit_cmd(git_ctx, "feat: commit hook\n")}},
            "executions": {
                "default": {
                    "repository": "repo",
                    "git": {
                        "branch": {"name": "feat/commit-hook", "base": "main"},
                        "commit": {"message_source": "commit-msg"},
                    },
                    "before": ["git:branch"],
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md", "after": ["git:commit"]}],
                }
            },
        },
    )
    result = _run_cli("run", "--config", str(git_ctx.config_path), cwd=git_ctx.repo)
    assert result.returncode == 0, result.stderr

    log = subprocess.run(
        ["git", "log", "--oneline", "feat/commit-hook"],
        cwd=git_ctx.repo, text=True, capture_output=True, check=True,
    )
    assert len(log.stdout.strip().splitlines()) == 2  # initial + new commit
    assert git_ctx.target_file.read_text() == "updated\n"


@pytest.mark.slow
def test_git_commit_skips_when_tree_is_clean(git_ctx: SimpleNamespace) -> None:
    _write_config(
        git_ctx,
        {
            "version": "6",
            "agent": {"command": f"{_q(CLI_PYTHON)} {_q(git_ctx.noop_script)} {{prompt_file}}"},
            "repositories": {"repo": {"path": str(git_ctx.repo)}},
            "context_sources": {"commit-msg": {"command": _emit_cmd(git_ctx, "feat: noop\n")}},
            "executions": {
                "default": {
                    "repository": "repo",
                    "git": {
                        "branch": {"name": "feat/clean-tree", "base": "main"},
                        "commit": {"message_source": "commit-msg"},
                    },
                    "before": ["git:branch"],
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md", "after": ["git:commit"]}],
                }
            },
        },
    )
    result = _run_cli("run", "--config", str(git_ctx.config_path), cwd=git_ctx.repo)
    assert result.returncode == 0, result.stderr

    log = subprocess.run(
        ["git", "log", "--oneline", "feat/clean-tree"],
        cwd=git_ctx.repo, text=True, capture_output=True, check=True,
    )
    # Only the initial commit — git:commit skips when tree is clean
    assert len(log.stdout.strip().splitlines()) == 1


# ---------------------------------------------------------------------------
# Integration: git:push in execution after hook
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_git_push_in_after_hook_pushes_branch(git_ctx: SimpleNamespace) -> None:
    _write_config(
        git_ctx,
        {
            "version": "6",
            "agent": {"command": _agent_cmd(git_ctx.mutate_script, git_ctx.target_file)},
            "repositories": {"repo": {"path": str(git_ctx.repo)}},
            "context_sources": {"commit-msg": {"command": _emit_cmd(git_ctx, "feat: push hook\n")}},
            "executions": {
                "default": {
                    "repository": "repo",
                    "git": {
                        "branch": {"name": "feat/push-hook", "base": "main"},
                        "commit": {"message_source": "commit-msg"},
                        "push": {"remote": "origin"},
                    },
                    "before": ["git:branch"],
                    "after": ["git:push"],
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md", "after": ["git:commit"]}],
                }
            },
        },
    )
    result = _run_cli("run", "--config", str(git_ctx.config_path), cwd=git_ctx.repo)
    assert result.returncode == 0, result.stderr

    remote_log = subprocess.run(
        ["git", "log", "--oneline", "refs/heads/feat/push-hook"],
        cwd=git_ctx.remote_repo, text=True, capture_output=True, check=True,
    )
    assert len(remote_log.stdout.strip().splitlines()) == 2  # initial + commit


# ---------------------------------------------------------------------------
# Integration: execution-level on_failure hook
# ---------------------------------------------------------------------------


def test_execution_on_failure_hook_runs_on_error(git_ctx: SimpleNamespace) -> None:
    failure_marker = git_ctx.repo / "failure_ran.txt"
    _write_config(
        git_ctx,
        {
            "version": "6",
            "agent": {"command": f"{_q(CLI_PYTHON)} {_q(git_ctx.fail_script)} {{prompt_file}}"},
            "repositories": {"repo": {"path": str(git_ctx.repo)}},
            "executions": {
                "default": {
                    "repository": "repo",
                    "on_failure": [
                        f"{_q(CLI_PYTHON)} {_q(git_ctx.marker_script)} {_q(failure_marker)}"
                    ],
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                }
            },
        },
    )
    result = _run_cli("run", "--config", str(git_ctx.config_path), cwd=git_ctx.repo)
    assert result.returncode == 1
    assert failure_marker.exists(), "on_failure hook should have created the marker file"


# ---------------------------------------------------------------------------
# Integration: git:pr in execution after hook (using a fake gh)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_git_pr_in_after_hook_invokes_gh(git_ctx: SimpleNamespace, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_log = tmp_path / "gh-log.json"

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

    _write_config(
        git_ctx,
        {
            "version": "6",
            "agent": {"command": _agent_cmd(git_ctx.mutate_script, git_ctx.target_file)},
            "repositories": {"repo": {"path": str(git_ctx.repo)}},
            "context_sources": {"commit-msg": {"command": _emit_cmd(git_ctx, "feat: pr hook\n\nPR body")}},
            "executions": {
                "default": {
                    "repository": "repo",
                    "git": {
                        "branch": {"name": "feat/pr-hook", "base": "main"},
                        "commit": {"message_source": "commit-msg"},
                        "push": {"remote": "origin"},
                        "pr": {"base": "main", "draft": False},
                    },
                    "before": ["git:branch"],
                    "after": ["git:commit", "git:push", "git:pr"],
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                }
            },
        },
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["GH_LOG"] = str(gh_log)
    result = subprocess.run(
        [str(CLI_PYTHON), str(CLI_PATH), "run", "--config", str(git_ctx.config_path)],
        cwd=git_ctx.repo, text=True, capture_output=True, check=False, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert gh_log.exists(), "fake gh should have been invoked"

    import json
    invocation = json.loads(gh_log.read_text())
    assert invocation["args"][:2] == ["pr", "create"]
    assert "--base" in invocation["args"]
    assert "main" in invocation["args"]
    assert "--head" in invocation["args"]
    assert "feat/pr-hook" in invocation["args"]
    assert invocation["args"][invocation["args"].index("--title") + 1] == "feat: pr hook"
    assert "PR body" in invocation["body"]


# ---------------------------------------------------------------------------
# Runtime error: git:push without prior git:branch
# ---------------------------------------------------------------------------


def test_git_push_without_branch_raises_at_runtime(git_ctx: SimpleNamespace) -> None:
    _write_config(
        git_ctx,
        {
            "version": "6",
            "agent": {"command": _agent_cmd(git_ctx.mutate_script, git_ctx.target_file)},
            "repositories": {"repo": {"path": str(git_ctx.repo)}},
            "context_sources": {"commit-msg": {"command": _emit_cmd(git_ctx, "feat: no-branch\n")}},
            "executions": {
                "default": {
                    "repository": "repo",
                    "git": {
                        "branch": {"name": "feat/no-branch", "base": "main"},
                        "commit": {"message_source": "commit-msg"},
                        "push": {"remote": "origin"},
                    },
                    # git:push without git:branch — should fail at runtime
                    "after": ["git:push"],
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                }
            },
        },
    )
    result = _run_cli("run", "--config", str(git_ctx.config_path), cwd=git_ctx.repo)
    assert result.returncode == 1
    assert "git:push requires git:branch" in result.stderr
