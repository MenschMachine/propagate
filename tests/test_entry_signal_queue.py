from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from propagate_app.models import (
    ActiveSignal,
    AgentConfig,
    Config,
    ExecutionConfig,
    ExecutionSignalConfig,
    RepositoryConfig,
    SignalConfig,
    SignalFieldConfig,
    SubTaskConfig,
)
from propagate_app.serve import _serve_loop
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
        agent=AgentConfig(agents={"default": "echo test"}, default_agent="default"),
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


def test_entry_signal_queue_roundtrip_and_clear(tmp_path):
    from propagate_app.entry_signal_queue import (
        clear_entry_signal_queue,
        dequeue_entry_signal,
        enqueue_entry_signal,
        load_entry_signal_queue,
    )

    config_path = tmp_path / "propagate.yaml"
    config_path.write_text("version: '6'\n", encoding="utf-8")

    enqueue_entry_signal(
        config_path,
        initial_execution="detect",
        active_signal=ActiveSignal(signal_type="push", payload={"repository": "a/b"}, source="external"),
        metadata={"chat_id": "1"},
    )
    enqueue_entry_signal(
        config_path,
        initial_execution="detect",
        active_signal=ActiveSignal(signal_type="push", payload={"repository": "a/c"}, source="external"),
        metadata={"chat_id": "2"},
    )

    loaded = load_entry_signal_queue(config_path)
    assert len(loaded) == 2
    assert loaded[0].metadata == {"chat_id": "1"}
    assert loaded[1].metadata == {"chat_id": "2"}

    popped = dequeue_entry_signal(config_path)
    assert popped is not None
    assert popped.metadata == {"chat_id": "1"}
    assert len(load_entry_signal_queue(config_path)) == 1

    clear_entry_signal_queue(config_path)
    assert load_entry_signal_queue(config_path) == []


@pytest.mark.slow
def test_serve_drains_persisted_entry_queue_on_startup(tmp_path):
    from propagate_app.entry_signal_queue import enqueue_entry_signal

    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a], signals={"go": signal_cfg})
    enqueue_entry_signal(
        config.config_path,
        initial_execution="a",
        active_signal=ActiveSignal(signal_type="go", payload={}, source="external"),
        metadata={"chat_id": "55"},
    )

    address = "ipc:///tmp/propagate-test-serve-queue-startup.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()
    call_count = 0

    def mock_run_execution(execution, runtime_context, execution_status=None, on_phase_completed=None, on_runtime_context_updated=None, on_tasks_reset=None, skip_task_ids=None):
        nonlocal call_count
        call_count += 1
        shutdown.set()
        return runtime_context

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)

    assert call_count == 1


@pytest.mark.slow
def test_serve_entry_signals_run_in_fifo_order(tmp_path):
    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(name="go", payload={"n": SignalFieldConfig(field_type="number", required=True)})
    config = make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    address = "ipc:///tmp/propagate-test-serve-queue-fifo.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()
    observed = []

    def mock_run_execution(execution, runtime_context, execution_status=None, on_phase_completed=None, on_runtime_context_updated=None, on_tasks_reset=None, skip_task_ids=None):
        observed.append(runtime_context.active_signal.payload["n"])
        if len(observed) == 2:
            shutdown.set()
        time.sleep(0.15)
        return runtime_context

    def send_two_signals():
        time.sleep(0.05)
        push = connect_push_socket(address)
        send_signal(push, "go", {"n": 1})
        send_signal(push, "go", {"n": 2})
        close_push_socket(push)

    sender = threading.Thread(target=send_two_signals)
    sender.start()
    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    assert observed == [1, 2]
