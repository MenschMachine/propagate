import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from propagate_app.errors import PropagateError
from propagate_app.models import (
    ActiveSignal,
    AgentConfig,
    Config,
    ExecutionConfig,
    ExecutionScheduleState,
    PropagationTriggerConfig,
    RepositoryConfig,
    RunState,
    RuntimeContext,
    SignalConfig,
    SubTaskConfig,
)
from propagate_app.scheduler import (
    _drain_incoming_signals,
    has_pending_signal_triggers,
    run_execution_schedule,
)
from propagate_app.signal_transport import bind_pull_socket, close_pull_socket, close_push_socket, connect_push_socket, send_signal


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


def make_runtime_context(active_signal=None):
    return RuntimeContext(
        agent_command="echo test",
        context_sources={},
        active_signal=active_signal,
        initialized_signal_context_dirs=set(),
        working_dir=Path("/tmp"),
        context_root=Path("/tmp"),
    )


def test_has_pending_signal_triggers_true_when_unmatched_trigger(tmp_path):
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="pr-labeled")
    signal_cfg = SignalConfig(name="pr-labeled", payload={})
    config = make_config(tmp_path, [exec_a, exec_b], triggers=[trigger], signals={"pr-labeled": signal_cfg})
    from propagate_app.graph import build_execution_graph
    graph = build_execution_graph(config)
    schedule_state = ExecutionScheduleState(
        active_names={"a"},
        completed_names={"a"},
    )
    assert has_pending_signal_triggers(config, graph, schedule_state, set()) is True


def test_has_pending_signal_triggers_false_when_signal_already_received(tmp_path):
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="pr-labeled")
    signal_cfg = SignalConfig(name="pr-labeled", payload={})
    config = make_config(tmp_path, [exec_a, exec_b], triggers=[trigger], signals={"pr-labeled": signal_cfg})
    from propagate_app.graph import build_execution_graph
    graph = build_execution_graph(config)
    schedule_state = ExecutionScheduleState(
        active_names={"a"},
        completed_names={"a"},
    )
    assert has_pending_signal_triggers(config, graph, schedule_state, {"pr-labeled"}) is False


def test_has_pending_signal_triggers_false_when_target_already_active(tmp_path):
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="pr-labeled")
    signal_cfg = SignalConfig(name="pr-labeled", payload={})
    config = make_config(tmp_path, [exec_a, exec_b], triggers=[trigger], signals={"pr-labeled": signal_cfg})
    from propagate_app.graph import build_execution_graph
    graph = build_execution_graph(config)
    schedule_state = ExecutionScheduleState(
        active_names={"a", "b"},
        completed_names={"a"},
    )
    assert has_pending_signal_triggers(config, graph, schedule_state, set()) is False


def test_has_pending_signal_triggers_false_for_unconditional_trigger(tmp_path):
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal=None)
    config = make_config(tmp_path, [exec_a, exec_b], triggers=[trigger])
    from propagate_app.graph import build_execution_graph
    graph = build_execution_graph(config)
    schedule_state = ExecutionScheduleState(
        active_names={"a"},
        completed_names={"a"},
    )
    assert has_pending_signal_triggers(config, graph, schedule_state, set()) is False


def test_drain_incoming_signals_activates_triggers(tmp_path):
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="pr-labeled")
    signal_cfg = SignalConfig(name="pr-labeled", payload={})
    config = make_config(tmp_path, [exec_a, exec_b], triggers=[trigger], signals={"pr-labeled": signal_cfg})
    from propagate_app.graph import build_execution_graph
    graph = build_execution_graph(config)
    schedule_state = ExecutionScheduleState(
        active_names={"a"},
        completed_names={"a"},
    )
    received = set()

    address = "ipc:///tmp/propagate-test-drain.sock"
    pull = bind_pull_socket(address)
    push = connect_push_socket(address)
    try:
        send_signal(push, "pr-labeled", {})
        time.sleep(0.05)
        _drain_incoming_signals(pull, config, graph, schedule_state, received, make_runtime_context())
        assert "pr-labeled" in received
        assert "b" in schedule_state.active_names
    finally:
        close_push_socket(push)
        close_pull_socket(pull, address)


def test_drain_ignores_unknown_signals(tmp_path):
    exec_a = make_execution("a")
    config = make_config(tmp_path, [exec_a])
    from propagate_app.graph import build_execution_graph
    graph = build_execution_graph(config)
    schedule_state = ExecutionScheduleState(
        active_names={"a"},
        completed_names={"a"},
    )
    received = set()

    address = "ipc:///tmp/propagate-test-drain-unknown.sock"
    pull = bind_pull_socket(address)
    push = connect_push_socket(address)
    try:
        send_signal(push, "unknown-signal", {})
        time.sleep(0.05)
        _drain_incoming_signals(pull, config, graph, schedule_state, received, make_runtime_context())
        assert "unknown-signal" not in received
    finally:
        close_push_socket(push)
        close_pull_socket(pull, address)


def test_scheduler_waits_for_signal_then_runs_execution(tmp_path):
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="go")
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a, exec_b], triggers=[trigger], signals={"go": signal_cfg})

    address = "ipc:///tmp/propagate-test-scheduler-wait.sock"
    pull = bind_pull_socket(address)

    executions_run = []

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase, on_runtime_context_updated=None, on_tasks_reset=None):
        executions_run.append(execution.name)
        return runtime_context

    def send_delayed_signal():
        time.sleep(0.5)
        push = connect_push_socket(address)
        send_signal(push, "go", {})
        close_push_socket(push)

    sender = threading.Thread(target=send_delayed_signal)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            runtime_context = make_runtime_context()
            run_execution_schedule(config, "a", runtime_context, signal_socket=pull)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    assert executions_run == ["a", "b"]


def test_scheduler_exits_cleanly_without_signal_socket_when_signal_triggers_exist(tmp_path):
    """Without a signal socket, signal-gated triggers are unreachable. The scheduler
    completes what it can and exits."""
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="go")
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a, exec_b], triggers=[trigger], signals={"go": signal_cfg})

    executions_run = []

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase, on_runtime_context_updated=None, on_tasks_reset=None):
        executions_run.append(execution.name)
        return runtime_context

    with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
        runtime_context = make_runtime_context()
        run_execution_schedule(config, "a", runtime_context, signal_socket=None)

    assert executions_run == ["a"]


def test_scheduler_passes_signal_socket_into_execution_runtime_context(tmp_path):
    exec_a = make_execution("a")
    config = make_config(tmp_path, [exec_a])
    fake_socket = object()
    seen_signal_sockets = []

    def mock_run_execution(
        execution,
        runtime_context,
        completed_task_phases,
        on_phase_completed,
        completed_execution_phase,
        on_runtime_context_updated=None,
        on_tasks_reset=None,
    ):
        seen_signal_sockets.append(runtime_context.signal_socket)
        return runtime_context

    with (
        patch("propagate_app.scheduler._drain_incoming_signals", side_effect=lambda *args: args[-1]),
        patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution),
    ):
        runtime_context = make_runtime_context()
        run_execution_schedule(config, "a", runtime_context, signal_socket=fake_socket)

    assert seen_signal_sockets == [fake_socket]


def test_scheduler_deadlocks_when_dependency_never_completes(tmp_path):
    """A real deadlock: execution b depends on c, but c fails during execution."""
    exec_a = make_execution("a")
    exec_b = make_execution("b", depends_on=["c"])
    exec_c = make_execution("c")
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal=None)
    config = make_config(tmp_path, [exec_a, exec_b, exec_c], triggers=[trigger])

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase, on_runtime_context_updated=None, on_tasks_reset=None):
        if execution.name == "c":
            raise PropagateError("c failed")
        return runtime_context

    with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
        runtime_context = make_runtime_context()
        with pytest.raises(PropagateError, match="c failed"):
            run_execution_schedule(config, "a", runtime_context, signal_socket=None)


def test_scheduler_completes_without_waiting_when_no_signal_triggers(tmp_path):
    exec_a = make_execution("a")
    exec_b = make_execution("b", depends_on=["a"])
    config = make_config(tmp_path, [exec_a, exec_b])

    executions_run = []

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase, on_runtime_context_updated=None, on_tasks_reset=None):
        executions_run.append(execution.name)
        return runtime_context

    with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
        runtime_context = make_runtime_context()
        run_execution_schedule(config, "b", runtime_context)

    assert executions_run == ["a", "b"]


def test_multiple_signals_activate_different_triggers(tmp_path):
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    exec_c = make_execution("c")
    trigger_b = PropagationTriggerConfig(after="a", run="b", on_signal="signal-1")
    trigger_c = PropagationTriggerConfig(after="a", run="c", on_signal="signal-2")
    signals = {
        "signal-1": SignalConfig(name="signal-1", payload={}),
        "signal-2": SignalConfig(name="signal-2", payload={}),
    }
    config = make_config(tmp_path, [exec_a, exec_b, exec_c], triggers=[trigger_b, trigger_c], signals=signals)

    address = "ipc:///tmp/propagate-test-multi-signal.sock"
    pull = bind_pull_socket(address)

    executions_run = []

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase, on_runtime_context_updated=None, on_tasks_reset=None):
        executions_run.append(execution.name)
        return runtime_context

    def send_delayed_signals():
        time.sleep(0.3)
        push = connect_push_socket(address)
        send_signal(push, "signal-1", {})
        time.sleep(0.3)
        send_signal(push, "signal-2", {})
        close_push_socket(push)

    sender = threading.Thread(target=send_delayed_signals)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            runtime_context = make_runtime_context()
            run_execution_schedule(config, "a", runtime_context, signal_socket=pull)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    assert "a" in executions_run
    assert "b" in executions_run
    assert "c" in executions_run


def test_resume_restores_received_signal_types(tmp_path):
    """On resume, previously received signal types are restored so they don't need
    to be re-sent."""
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    exec_c = make_execution("c")
    trigger_b = PropagationTriggerConfig(after="a", run="b", on_signal="signal-1")
    trigger_c = PropagationTriggerConfig(after="b", run="c", on_signal="signal-2")
    signals = {
        "signal-1": SignalConfig(name="signal-1", payload={}),
        "signal-2": SignalConfig(name="signal-2", payload={}),
    }
    config = make_config(tmp_path, [exec_a, exec_b, exec_c], triggers=[trigger_b, trigger_c], signals=signals)

    # Simulate a resume where "a" and "b" completed, signal-1 was already received,
    # and we're waiting for signal-2.
    run_state = RunState(
        config_path=config.config_path,
        initial_execution="a",
        schedule=ExecutionScheduleState(
            active_names={"a", "b"},
            completed_names={"a", "b"},
        ),
        active_signal=None,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
        received_signal_types={"signal-1"},
    )

    address = "ipc:///tmp/propagate-test-resume-signals.sock"
    pull = bind_pull_socket(address)

    executions_run = []

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase, on_runtime_context_updated=None, on_tasks_reset=None):
        executions_run.append(execution.name)
        return runtime_context

    def send_delayed_signal():
        time.sleep(0.3)
        push = connect_push_socket(address)
        # Only send signal-2; signal-1 should be restored from run state
        send_signal(push, "signal-2", {})
        close_push_socket(push)

    sender = threading.Thread(target=send_delayed_signal)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            runtime_context = make_runtime_context()
            run_execution_schedule(config, "a", runtime_context, run_state=run_state, signal_socket=pull)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    # Only "c" should run — "a" and "b" were already completed
    assert executions_run == ["c"]


def test_scheduler_uses_updated_signal_for_execution_after_hooks_and_triggers(tmp_path):
    exec_a = make_execution("a")
    exec_b = make_execution("b")
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="pull_request.labeled", when={"label": "approved"})
    signals = {
        "pull_request.labeled": SignalConfig(
            name="pull_request.labeled",
            payload={},
        ),
    }
    config = make_config(tmp_path, [exec_a, exec_b], triggers=[trigger], signals=signals)
    executions_run = []

    final_ctx = make_runtime_context(
        active_signal=ActiveSignal(
            signal_type="pull_request.labeled",
            payload={"label": "approved", "pr_number": 99},
            source="external",
        )
    )

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase, on_runtime_context_updated=None, on_tasks_reset=None):
        executions_run.append(execution.name)
        if execution.name == "a":
            return final_ctx
        return runtime_context

    with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
        runtime_context = make_runtime_context(
            active_signal=ActiveSignal(
                signal_type="pull_request.labeled",
                payload={"label": "suggestions_needed", "pr_number": 1},
                source="initial",
            )
        )
        run_execution_schedule(config, "a", runtime_context)

    assert executions_run == ["a", "b"]


def test_scheduler_persists_updated_signal_to_run_state(tmp_path):
    exec_a = make_execution("a")
    config = make_config(tmp_path, [exec_a])
    run_state = RunState(
        config_path=config.config_path,
        initial_execution="a",
        schedule=ExecutionScheduleState(active_names=set(), completed_names=set()),
        active_signal=ActiveSignal(signal_type="pull_request.labeled", payload={"label": "initial"}, source="initial"),
        cloned_repos={},
        initialized_signal_context_dirs=set(),
    )

    updated_ctx = make_runtime_context(
        active_signal=ActiveSignal(
            signal_type="pull_request.labeled",
            payload={"label": "approved", "pr_number": 99},
            source="external",
        )
    )

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase, on_runtime_context_updated=None, on_tasks_reset=None):
        if on_runtime_context_updated is not None:
            on_runtime_context_updated(updated_ctx)
        return updated_ctx

    with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
        runtime_context = make_runtime_context(
            active_signal=ActiveSignal(signal_type="pull_request.labeled", payload={"label": "initial"}, source="initial")
        )
        run_execution_schedule(config, "a", runtime_context, run_state=run_state)

    assert run_state.active_signal == updated_ctx.active_signal
