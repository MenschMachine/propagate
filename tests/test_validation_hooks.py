from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from propagate_app.config_executions import parse_hook_actions
from propagate_app.context_store import ensure_context_dir, write_context_value
from propagate_app.errors import PropagateError
from propagate_app.models import ActiveSignal, RuntimeContext
from propagate_app.validation_hooks import run_validate_hook_command


def _make_runtime_context(tmp_path: Path, active_signal: ActiveSignal | None = None) -> RuntimeContext:
    context_root = tmp_path / "context"
    ensure_context_dir(context_root)
    return RuntimeContext(
        agent_command="echo test",
        context_sources={},
        active_signal=active_signal,
        initialized_signal_context_dirs=set(),
        working_dir=tmp_path,
        context_root=context_root,
        execution_name="current",
        task_id="",
    )


def test_parse_hook_actions_accepts_validate_github_pr(tmp_path):
    result = parse_hook_actions(
        ["validate:github-pr repo=MenschMachine/pdfdancer-api pr_from=signal.pr_number require_merged=true"],
        "execution 'ex'.sub_tasks[0]",
        "before",
        set(),
    )
    assert result == ["validate:github-pr repo=MenschMachine/pdfdancer-api pr_from=signal.pr_number require_merged=true"]


def test_parse_hook_actions_rejects_invalid_validate_github_pr(tmp_path):
    with pytest.raises(PropagateError, match="requires exactly one of 'repo=<owner/name>' or 'repo_from=<source>'"):
        parse_hook_actions(
            ["validate:github-pr pr_from=signal.pr_number"],
            "execution 'ex'.sub_tasks[0]",
            "before",
            set(),
        )


def test_parse_hook_actions_rejects_unknown_validate_command(tmp_path):
    with pytest.raises(PropagateError, match="unknown validation command"):
        parse_hook_actions(
            ["validate:not-a-real-command repo=MenschMachine/pdfdancer-api pr_from=signal.pr_number"],
            "execution 'ex'.sub_tasks[0]",
            "before",
            set(),
        )


def test_parse_hook_actions_accepts_validate_context_key(tmp_path):
    result = parse_hook_actions(
        ["validate:context-key key=:pipeline-decision scope=global"],
        "execution 'ex'.sub_tasks[0]",
        "before",
        set(),
    )
    assert result == ["validate:context-key key=:pipeline-decision scope=global"]


def test_parse_hook_actions_rejects_invalid_context_key_scope(tmp_path):
    with pytest.raises(PropagateError, match="scope must be 'global', 'execution', or 'execution/task'"):
        parse_hook_actions(
            ["validate:context-key key=:pipeline-decision scope=bad/scope/extra"],
            "execution 'ex'.sub_tasks[0]",
            "before",
            set(),
        )


def test_run_validate_hook_command_resolves_signal_pr_number(tmp_path):
    runtime_context = _make_runtime_context(
        tmp_path,
        ActiveSignal(signal_type="pull_request.closed", payload={"pr_number": 42}, source="test"),
    )
    completed = subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout='{"number":42,"state":"MERGED","mergedAt":"2026-03-20T00:00:00Z"}',
    )
    with patch("propagate_app.validation_hooks.run_process_command", return_value=completed) as mock_run:
        run_validate_hook_command(
            "validate:github-pr repo=MenschMachine/pdfdancer-api pr_from=signal.pr_number require_merged=true",
            runtime_context,
        )
    assert mock_run.call_args.args[0][0:6] == ["gh", "pr", "view", "42", "--repo", "MenschMachine/pdfdancer-api"]


def test_run_validate_hook_command_resolves_repo_from_context(tmp_path):
    runtime_context = _make_runtime_context(
        tmp_path,
        ActiveSignal(signal_type="pull_request.closed", payload={"pr_number": 42}, source="test"),
    )
    write_context_value(runtime_context.context_root, ":source-repository", "MenschMachine/pdfdancer-api")
    completed = subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout='{"number":42,"state":"MERGED","mergedAt":"2026-03-20T00:00:00Z"}',
    )
    with patch("propagate_app.validation_hooks.run_process_command", return_value=completed) as mock_run:
        run_validate_hook_command(
            "validate:github-pr repo_from=context:global/:source-repository pr_from=signal.pr_number require_merged=true",
            runtime_context,
        )
    assert mock_run.call_args.args[0][5] == "MenschMachine/pdfdancer-api"


def test_parse_hook_actions_rejects_github_pr_with_repo_and_repo_from(tmp_path):
    with pytest.raises(PropagateError, match="requires exactly one of 'repo=<owner/name>' or 'repo_from=<source>'"):
        parse_hook_actions(
            ["validate:github-pr repo=MenschMachine/pdfdancer-api repo_from=context:global/:source-repository pr_from=signal.pr_number"],
            "execution 'ex'.sub_tasks[0]",
            "before",
            set(),
        )


def test_run_validate_hook_command_resolves_context_pr_number(tmp_path):
    runtime_context = _make_runtime_context(tmp_path)
    triage_dir = runtime_context.context_root / "triage-api-pr"
    ensure_context_dir(triage_dir)
    write_context_value(triage_dir, ":source-api-pr-number", "84")
    completed = subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout='{"number":84,"state":"MERGED","mergedAt":"2026-03-20T00:00:00Z"}',
    )
    with patch("propagate_app.validation_hooks.run_process_command", return_value=completed) as mock_run:
        run_validate_hook_command(
            "validate:github-pr repo=MenschMachine/pdfdancer-api pr_from=context:triage-api-pr/:source-api-pr-number require_merged=true",
            runtime_context,
        )
    assert mock_run.call_args.args[0][3] == "84"


def test_run_validate_hook_command_fails_when_pr_not_merged(tmp_path):
    runtime_context = _make_runtime_context(
        tmp_path,
        ActiveSignal(signal_type="pull_request.closed", payload={"pr_number": 42}, source="test"),
    )
    completed = subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout='{"number":42,"state":"OPEN","mergedAt":null}',
    )
    with patch("propagate_app.validation_hooks.run_process_command", return_value=completed):
        with pytest.raises(PropagateError, match="is not merged"):
            run_validate_hook_command(
                "validate:github-pr repo=MenschMachine/pdfdancer-api pr_from=signal.pr_number require_merged=true",
                runtime_context,
            )


def test_run_validate_context_key_reads_global_scope(tmp_path):
    runtime_context = _make_runtime_context(tmp_path)
    write_context_value(runtime_context.context_root, ":pipeline-decision", "FULL: test")
    run_validate_hook_command(
        "validate:context-key key=:pipeline-decision scope=global",
        runtime_context,
    )


def test_run_validate_context_key_checks_equals(tmp_path):
    runtime_context = _make_runtime_context(tmp_path)
    write_context_value(runtime_context.context_root, ":pipeline-decision", "FULL: test")
    run_validate_hook_command(
        "validate:context-key key=:pipeline-decision scope=global 'equals=FULL: test'",
        runtime_context,
    )


def test_run_validate_context_key_fails_when_empty(tmp_path):
    runtime_context = _make_runtime_context(tmp_path)
    write_context_value(runtime_context.context_root, ":pipeline-decision", "")
    with pytest.raises(PropagateError, match="is empty"):
        run_validate_hook_command(
            "validate:context-key key=:pipeline-decision scope=global",
            runtime_context,
        )


def test_run_validate_context_key_reads_execution_scope_by_name(tmp_path):
    runtime_context = _make_runtime_context(tmp_path)
    execution_dir = runtime_context.context_root / "triage-api-pr"
    ensure_context_dir(execution_dir)
    write_context_value(execution_dir, ":pipeline-decision", "DOCS: test")
    run_validate_hook_command(
        "validate:context-key key=:pipeline-decision scope=triage-api-pr 'equals=DOCS: test'",
        runtime_context,
    )
