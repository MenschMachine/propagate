import subprocess
from unittest.mock import MagicMock, patch

import pytest

from propagate_app.config_signals import parse_signal_config
from propagate_app.errors import PropagateError
from propagate_app.graph import build_execution_graph
from propagate_app.models import (
    AgentConfig,
    Config,
    ExecutionConfig,
    ExecutionScheduleState,
    PropagationTriggerConfig,
    RepositoryConfig,
    SignalConfig,
    SignalFieldConfig,
    SubTaskConfig,
)
from propagate_app.signal_reconcile import (
    reconcile_pending_signals,
)


def make_config(tmp_path, executions, triggers=None, signals=None):
    config_path = tmp_path / "propagate.yaml"
    config_path.touch()
    repos = {}
    for exec_cfg in executions:
        if exec_cfg.repository not in repos:
            repo_dir = tmp_path / exec_cfg.repository
            repo_dir.mkdir(exist_ok=True)
            repos[exec_cfg.repository] = RepositoryConfig(name=exec_cfg.repository, path=repo_dir)
    return Config(
        version="6",
        agent=AgentConfig(command="echo test"),
        repositories=repos,
        context_sources={},
        signals=signals or {},
        propagation_triggers=triggers or [],
        executions={e.name: e for e in executions},
        config_path=config_path,
    )


def make_execution(name, repository="repo", depends_on=None, signals=None):
    return ExecutionConfig(
        name=name,
        repository=repository,
        depends_on=depends_on or [],
        signals=signals or [],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )


def _setup(tmp_path, check=None, when=None):
    """Build config/graph/state for a simple A -> B trigger with on_signal + when."""
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    trigger = PropagationTriggerConfig(
        after="a", run="b", on_signal="pr.labeled",
        when=when if when is not None else {"label": "deploy"},
    )
    signal_cfg = SignalConfig(
        name="pr.labeled",
        payload={"label": SignalFieldConfig(field_type="string", required=True)},
        check=check,
    )
    config = make_config(tmp_path, [exec_a, exec_b], triggers=[trigger], signals={"pr.labeled": signal_cfg})
    graph = build_execution_graph(config)
    schedule_state = ExecutionScheduleState(
        active_names={"a"},
        completed_names={"a"},
    )
    received = set()
    return config, graph, schedule_state, received


def test_reconcile_fires_when_check_exits_zero(tmp_path):
    config, graph, state, received = _setup(tmp_path, check="echo {label}")
    mock_result = MagicMock(returncode=0)
    with patch("propagate_app.signal_reconcile.subprocess.run", return_value=mock_result):
        result = reconcile_pending_signals(config, graph, state, received)
    assert result is True
    assert "b" in state.active_names
    assert "pr.labeled" in received


def test_reconcile_skips_when_check_exits_nonzero(tmp_path):
    config, graph, state, received = _setup(tmp_path, check="echo {label}")
    mock_result = MagicMock(returncode=1)
    with patch("propagate_app.signal_reconcile.subprocess.run", return_value=mock_result):
        result = reconcile_pending_signals(config, graph, state, received)
    assert result is False
    assert "b" not in state.active_names


def test_reconcile_skips_signal_without_check(tmp_path):
    config, graph, state, received = _setup(tmp_path, check=None)
    result = reconcile_pending_signals(config, graph, state, received)
    assert result is False
    assert "b" not in state.active_names


def test_reconcile_skips_trigger_without_when(tmp_path):
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="pr.labeled", when=None)
    signal_cfg = SignalConfig(
        name="pr.labeled",
        payload={"label": SignalFieldConfig(field_type="string", required=True)},
        check="echo {label}",
    )
    config = make_config(tmp_path, [exec_a, exec_b], triggers=[trigger], signals={"pr.labeled": signal_cfg})
    graph = build_execution_graph(config)
    state = ExecutionScheduleState(active_names={"a"}, completed_names={"a"})
    received = set()
    result = reconcile_pending_signals(config, graph, state, received)
    assert result is False


def test_reconcile_skips_when_placeholder_missing(tmp_path):
    config, graph, state, received = _setup(tmp_path, check="echo {foo}")
    result = reconcile_pending_signals(config, graph, state, received)
    assert result is False
    assert "b" not in state.active_names


def test_reconcile_handles_os_error(tmp_path):
    config, graph, state, received = _setup(tmp_path, check="echo {label}")
    with patch("propagate_app.signal_reconcile.subprocess.run", side_effect=OSError("fail")):
        result = reconcile_pending_signals(config, graph, state, received)
    assert result is False


def test_reconcile_returns_false_no_pending(tmp_path):
    exec_a = make_execution("a")
    config = make_config(tmp_path, [exec_a])
    graph = build_execution_graph(config)
    state = ExecutionScheduleState(active_names={"a"}, completed_names={"a"})
    received = set()
    result = reconcile_pending_signals(config, graph, state, received)
    assert result is False


def test_reconcile_quotes_when_values(tmp_path):
    config, graph, state, received = _setup(
        tmp_path,
        check="echo {label}",
        when={"label": "; rm -rf /"},
    )
    mock_result = MagicMock(returncode=0)
    with patch("propagate_app.signal_reconcile.subprocess.run", return_value=mock_result) as mock_run:
        reconcile_pending_signals(config, graph, state, received)
    call_args = mock_run.call_args
    command = call_args[0][0]
    # shlex.quote wraps the dangerous value in single quotes
    assert "'; rm -rf /'" in command


def test_reconcile_does_not_recheck_successful_trigger(tmp_path):
    config, graph, state, received = _setup(tmp_path, check="echo {label}")
    reconciled_triggers = set()
    mock_result = MagicMock(returncode=0)
    with patch("propagate_app.signal_reconcile.subprocess.run", return_value=mock_result) as mock_run:
        reconcile_pending_signals(config, graph, state, received, reconciled_triggers)
        assert mock_run.call_count == 1
        # Second call should skip — trigger already reconciled.
        reconcile_pending_signals(config, graph, state, received, reconciled_triggers)
        assert mock_run.call_count == 1


def test_reconcile_retries_failed_check(tmp_path):
    config, graph, state, received = _setup(tmp_path, check="echo {label}")
    reconciled_triggers = set()
    fail_result = MagicMock(returncode=1)
    success_result = MagicMock(returncode=0)
    with patch("propagate_app.signal_reconcile.subprocess.run", return_value=fail_result) as mock_run:
        result = reconcile_pending_signals(config, graph, state, received, reconciled_triggers)
        assert result is False
        assert mock_run.call_count == 1
    # Failed checks are not added to reconciled_triggers, so retry works.
    with patch("propagate_app.signal_reconcile.subprocess.run", return_value=success_result):
        result = reconcile_pending_signals(config, graph, state, received, reconciled_triggers)
        assert result is True
        assert "b" in state.active_names


def test_reconcile_handles_timeout(tmp_path):
    config, graph, state, received = _setup(tmp_path, check="echo {label}")
    with patch(
        "propagate_app.signal_reconcile.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="echo", timeout=30),
    ):
        result = reconcile_pending_signals(config, graph, state, received)
    assert result is False


def test_check_command_parsed():
    signal_cfg = parse_signal_config("test-signal", {
        "payload": {"repo": {"type": "string", "required": True}},
        "check": "gh pr view --repo {repo}",
    })
    assert signal_cfg.check == "gh pr view --repo {repo}"


def test_check_command_rejects_non_string():
    with pytest.raises(PropagateError, match="check must be a string"):
        parse_signal_config("test-signal", {
            "payload": {"repo": {"type": "string", "required": True}},
            "check": 42,
        })
