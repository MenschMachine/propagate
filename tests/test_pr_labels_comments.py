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

from propagate_app.config_executions import parse_hook_actions
from propagate_app.errors import PropagateError

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "propagate.py"
CLI_PYTHON = REPO_ROOT / "venv" / "bin" / "python"
if not CLI_PYTHON.exists():
    CLI_PYTHON = Path(sys.executable)


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def _q(path: Path) -> str:
    return shlex.quote(str(path))


# ---------------------------------------------------------------------------
# Parse-time tests (parse_hook_actions direct calls)
# ---------------------------------------------------------------------------


def test_pr_labels_add_plain_labels_accepted() -> None:
    actions = parse_hook_actions(
        ["git:pr-labels-add bug enhancement"],
        "Test", "after", set(),
    )
    assert actions == ["git:pr-labels-add bug enhancement"]


def test_pr_labels_add_context_key_accepted() -> None:
    actions = parse_hook_actions(
        ["git:pr-labels-add :my-label"],
        "Test", "after", set(),
    )
    assert actions == ["git:pr-labels-add :my-label"]


def test_pr_labels_add_mixed_args_accepted() -> None:
    actions = parse_hook_actions(
        ["git:pr-labels-add bug :extra-label enhancement"],
        "Test", "after", set(),
    )
    assert actions == ["git:pr-labels-add bug :extra-label enhancement"]


def test_pr_labels_add_no_args_raises() -> None:
    with pytest.raises(PropagateError, match="requires at least one label argument"):
        parse_hook_actions(["git:pr-labels-add"], "Test", "after", set())


def test_pr_labels_remove_plain_label_accepted() -> None:
    actions = parse_hook_actions(
        ["git:pr-labels-remove in-progress"],
        "Test", "after", set(),
    )
    assert actions == ["git:pr-labels-remove in-progress"]


def test_pr_labels_remove_no_args_raises() -> None:
    with pytest.raises(PropagateError, match="requires at least one label argument"):
        parse_hook_actions(["git:pr-labels-remove"], "Test", "after", set())


def test_pr_labels_list_context_key_accepted() -> None:
    actions = parse_hook_actions(
        ["git:pr-labels-list :current-labels"],
        "Test", "after", set(),
    )
    assert actions == ["git:pr-labels-list :current-labels"]


def test_pr_labels_list_non_key_arg_raises() -> None:
    with pytest.raises(PropagateError, match="must be a ':'-prefixed context key"):
        parse_hook_actions(["git:pr-labels-list plain-arg"], "Test", "after", set())


def test_pr_labels_list_two_args_raises() -> None:
    with pytest.raises(PropagateError, match="requires exactly one argument"):
        parse_hook_actions(["git:pr-labels-list :key1 :key2"], "Test", "after", set())


def test_pr_labels_list_no_args_raises() -> None:
    with pytest.raises(PropagateError, match="requires exactly one argument"):
        parse_hook_actions(["git:pr-labels-list"], "Test", "after", set())


def test_pr_comment_add_context_key_accepted() -> None:
    actions = parse_hook_actions(
        ["git:pr-comment-add :review-summary"],
        "Test", "after", set(),
    )
    assert actions == ["git:pr-comment-add :review-summary"]


def test_pr_comment_add_non_key_arg_raises() -> None:
    with pytest.raises(PropagateError, match="must be a ':'-prefixed context key"):
        parse_hook_actions(["git:pr-comment-add plain"], "Test", "after", set())


def test_pr_comment_add_no_args_raises() -> None:
    with pytest.raises(PropagateError, match="requires exactly one argument"):
        parse_hook_actions(["git:pr-comment-add"], "Test", "after", set())


def test_pr_comments_list_context_key_accepted() -> None:
    actions = parse_hook_actions(
        ["git:pr-comments-list :all-comments"],
        "Test", "after", set(),
    )
    assert actions == ["git:pr-comments-list :all-comments"]


def test_pr_comments_list_non_key_arg_raises() -> None:
    with pytest.raises(PropagateError, match="must be a ':'-prefixed context key"):
        parse_hook_actions(["git:pr-comments-list plain"], "Test", "after", set())


def test_pr_comments_list_two_args_raises() -> None:
    with pytest.raises(PropagateError, match="requires exactly one argument"):
        parse_hook_actions(["git:pr-comments-list :k1 :k2"], "Test", "after", set())


def test_unknown_git_command_still_raises() -> None:
    with pytest.raises(PropagateError, match="unknown git command"):
        parse_hook_actions(["git:nope"], "Test", "after", set())


# ---------------------------------------------------------------------------
# Integration fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def pr_ctx(tmp_path: Path):
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

    noop_script = scripts_dir / "noop_agent.py"
    noop_script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).read_text()\n",
        encoding="utf-8",
    )

    emit_script = scripts_dir / "emit_text.py"
    emit_script.write_text("import sys\nsys.stdout.write(sys.argv[1])\n", encoding="utf-8")

    _run_git("init", "-b", "main", cwd=repo)
    _run_git("config", "user.name", "Propagate Tests", cwd=repo)
    _run_git("config", "user.email", "propagate@example.com", cwd=repo)
    subprocess.run(["git", "init", "--bare", str(remote_repo)], cwd=tmp_path, check=True, capture_output=True)
    _run_git("remote", "add", "origin", str(remote_repo), cwd=repo)

    (repo / "initial.txt").write_text("initial\n", encoding="utf-8")
    _run_git("add", "-A", cwd=repo)
    _run_git("commit", "-m", "initial commit", cwd=repo)
    _run_git("push", "--set-upstream", "origin", "main", cwd=repo)

    # bin dir for fake gh
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_log = tmp_path / "gh-log.jsonl"

    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "body = ''\n"
        "if '--body-file' in args:\n"
        "    body = Path(args[args.index('--body-file') + 1]).read_text()\n"
        "log_path = Path(os.environ['GH_LOG'])\n"
        "with open(log_path, 'a') as f:\n"
        "    f.write(json.dumps({'args': args, 'body': body}) + '\\n')\n"
        "# For view commands, output fake JSON to stdout\n"
        "if 'view' in args and '--json' in args:\n"
        "    json_field = args[args.index('--json') + 1]\n"
        "    if json_field == 'labels':\n"
        "        print(json.dumps({'labels': [{'name': 'bug'}, {'name': 'enhancement'}]}))\n"
        "    elif json_field == 'comments':\n"
        "        print(json.dumps({'comments': [{'id': 1, 'author': {'login': 'test'}, 'body': 'hello'}]}))\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    return SimpleNamespace(
        repo=repo,
        remote_repo=remote_repo,
        config_path=config_path,
        prompt_path=prompt_path,
        noop_script=noop_script,
        emit_script=emit_script,
        bin_dir=bin_dir,
        gh_log=gh_log,
    )


def _write_config(ctx: SimpleNamespace, config_data: dict) -> None:
    ctx.config_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.config_path.write_text(yaml.dump(config_data, sort_keys=False), encoding="utf-8")


def _emit_cmd(ctx: SimpleNamespace, text: str) -> str:
    return f"{_q(CLI_PYTHON)} {_q(ctx.emit_script)} {shlex.quote(text)}"


def _noop_cmd(ctx: SimpleNamespace) -> str:
    return f"{_q(CLI_PYTHON)} {_q(ctx.noop_script)} {{prompt_file}}"


def _run_with_fake_gh(ctx: SimpleNamespace) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{ctx.bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["GH_LOG"] = str(ctx.gh_log)
    return subprocess.run(
        [str(CLI_PYTHON), str(CLI_PATH), "run", "--config", str(ctx.config_path)],
        cwd=ctx.repo, text=True, capture_output=True, check=False, env=env,
    )


def _read_gh_log(ctx: SimpleNamespace) -> list[dict]:
    return [json.loads(line) for line in ctx.gh_log.read_text().splitlines() if line.strip()]


def _base_config(ctx: SimpleNamespace, extra_after: list[str]) -> dict:
    return {
        "version": "6",
        "agent": {"command": _noop_cmd(ctx)},
        "repositories": {"repo": {"path": str(ctx.repo)}},
        "context_sources": {"commit-msg": {"command": _emit_cmd(ctx, "feat: test\n")}},
        "executions": {
            "default": {
                "repository": "repo",
                "git": {
                    "branch": {"name": "feat/pr-test", "base": "main"},
                    "commit": {"message_source": "commit-msg"},
                    "push": {"remote": "origin"},
                    "pr": {"base": "main"},
                },
                "before": ["git:branch"],
                "after": ["git:push", "git:pr"] + extra_after,
                "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
            }
        },
    }


# ---------------------------------------------------------------------------
# Integration: git:pr-labels-add
# ---------------------------------------------------------------------------


def test_pr_labels_add_plain_label_invokes_gh(pr_ctx: SimpleNamespace) -> None:
    _write_config(pr_ctx, _base_config(pr_ctx, ["git:pr-labels-add bug"]))
    result = _run_with_fake_gh(pr_ctx)
    assert result.returncode == 0, result.stderr

    entries = _read_gh_log(pr_ctx)
    label_calls = [e for e in entries if "--add-label" in e["args"]]
    assert len(label_calls) == 1
    assert "bug" in label_calls[0]["args"]


def test_pr_labels_add_context_key_resolves(pr_ctx: SimpleNamespace) -> None:
    # Use a before hook to write context key so it's available at runtime
    context_root = pr_ctx.config_path.parent / ".propagate-context-propagate" / "default"
    write_cmd = f"mkdir -p {_q(context_root)} && printf 'from-context' > {_q(context_root / ':label-key')}"

    config = _base_config(pr_ctx, ["git:pr-labels-add :label-key"])
    config["executions"]["default"]["sub_tasks"][0]["before"] = [write_cmd]
    _write_config(pr_ctx, config)
    result = _run_with_fake_gh(pr_ctx)
    assert result.returncode == 0, result.stderr

    entries = _read_gh_log(pr_ctx)
    label_calls = [e for e in entries if "--add-label" in e["args"]]
    assert len(label_calls) == 1
    idx = label_calls[0]["args"].index("--add-label")
    assert label_calls[0]["args"][idx + 1] == "from-context"


def test_pr_labels_add_multiple_labels(pr_ctx: SimpleNamespace) -> None:
    _write_config(pr_ctx, _base_config(pr_ctx, ["git:pr-labels-add bug enhancement"]))
    result = _run_with_fake_gh(pr_ctx)
    assert result.returncode == 0, result.stderr

    entries = _read_gh_log(pr_ctx)
    label_calls = [e for e in entries if "--add-label" in e["args"]]
    assert len(label_calls) == 1
    idx = label_calls[0]["args"].index("--add-label")
    assert label_calls[0]["args"][idx + 1] == "bug,enhancement"


# ---------------------------------------------------------------------------
# Integration: git:pr-labels-remove
# ---------------------------------------------------------------------------


def test_pr_labels_remove_invokes_gh(pr_ctx: SimpleNamespace) -> None:
    _write_config(pr_ctx, _base_config(pr_ctx, ["git:pr-labels-remove needs-review"]))
    result = _run_with_fake_gh(pr_ctx)
    assert result.returncode == 0, result.stderr

    entries = _read_gh_log(pr_ctx)
    remove_calls = [e for e in entries if "--remove-label" in e["args"]]
    assert len(remove_calls) == 1
    idx = remove_calls[0]["args"].index("--remove-label")
    assert remove_calls[0]["args"][idx + 1] == "needs-review"


# ---------------------------------------------------------------------------
# Integration: git:pr-labels-list
# ---------------------------------------------------------------------------


def test_pr_labels_list_stores_to_context(pr_ctx: SimpleNamespace) -> None:
    _write_config(pr_ctx, _base_config(pr_ctx, ["git:pr-labels-list :stored-labels"]))
    result = _run_with_fake_gh(pr_ctx)
    assert result.returncode == 0, result.stderr

    context_root = pr_ctx.config_path.parent / ".propagate-context-propagate"
    stored = (context_root / "default" / ":stored-labels").read_text(encoding="utf-8")
    parsed = json.loads(stored)
    assert "labels" in parsed
    assert len(parsed["labels"]) == 2


# ---------------------------------------------------------------------------
# Integration: git:pr-comment-add
# ---------------------------------------------------------------------------


def test_pr_comment_add_reads_body_from_context(pr_ctx: SimpleNamespace) -> None:
    context_root = pr_ctx.config_path.parent / ".propagate-context-propagate" / "default"
    write_cmd = f"mkdir -p {_q(context_root)} && printf 'This is my comment body.' > {_q(context_root / ':body-key')}"

    config = _base_config(pr_ctx, ["git:pr-comment-add :body-key"])
    config["executions"]["default"]["sub_tasks"][0]["before"] = [write_cmd]
    _write_config(pr_ctx, config)
    result = _run_with_fake_gh(pr_ctx)
    assert result.returncode == 0, result.stderr

    entries = _read_gh_log(pr_ctx)
    comment_calls = [e for e in entries if e["args"][:2] == ["pr", "comment"] and "--body-file" in e["args"]]
    assert len(comment_calls) == 1
    assert comment_calls[0]["body"] == "This is my comment body."


# ---------------------------------------------------------------------------
# Integration: git:pr-comments-list
# ---------------------------------------------------------------------------


def test_pr_comments_list_stores_to_context(pr_ctx: SimpleNamespace) -> None:
    _write_config(pr_ctx, _base_config(pr_ctx, ["git:pr-comments-list :stored-comments"]))
    result = _run_with_fake_gh(pr_ctx)
    assert result.returncode == 0, result.stderr

    context_root = pr_ctx.config_path.parent / ".propagate-context-propagate"
    stored = (context_root / "default" / ":stored-comments").read_text(encoding="utf-8")
    parsed = json.loads(stored)
    assert "comments" in parsed
    assert parsed["comments"][0]["body"] == "hello"


# ---------------------------------------------------------------------------
# Integration: git:pr-labels-remove with :key
# ---------------------------------------------------------------------------


def test_pr_labels_remove_context_key_resolves(pr_ctx: SimpleNamespace) -> None:
    context_root = pr_ctx.config_path.parent / ".propagate-context-propagate" / "default"
    write_cmd = f"mkdir -p {_q(context_root)} && printf 'stale-label' > {_q(context_root / ':remove-key')}"

    config = _base_config(pr_ctx, ["git:pr-labels-remove :remove-key"])
    config["executions"]["default"]["sub_tasks"][0]["before"] = [write_cmd]
    _write_config(pr_ctx, config)
    result = _run_with_fake_gh(pr_ctx)
    assert result.returncode == 0, result.stderr

    entries = _read_gh_log(pr_ctx)
    remove_calls = [e for e in entries if "--remove-label" in e["args"]]
    assert len(remove_calls) == 1
    idx = remove_calls[0]["args"].index("--remove-label")
    assert remove_calls[0]["args"][idx + 1] == "stale-label"


# ---------------------------------------------------------------------------
# Runtime validation: resolved label with invalid content
# ---------------------------------------------------------------------------


def test_pr_labels_add_empty_resolved_label_raises(pr_ctx: SimpleNamespace) -> None:
    context_root = pr_ctx.config_path.parent / ".propagate-context-propagate" / "default"
    write_cmd = f"mkdir -p {_q(context_root)} && printf '' > {_q(context_root / ':empty-label')}"

    config = _base_config(pr_ctx, ["git:pr-labels-add :empty-label"])
    config["executions"]["default"]["sub_tasks"][0]["before"] = [write_cmd]
    _write_config(pr_ctx, config)
    result = _run_with_fake_gh(pr_ctx)
    assert result.returncode == 1
    assert "resolved to an empty label" in result.stderr
