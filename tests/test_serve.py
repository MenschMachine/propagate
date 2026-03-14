import threading
import time
from unittest.mock import patch

from propagate_app.errors import PropagateError
from propagate_app.models import (
    AgentConfig,
    Config,
    ExecutionConfig,
    ExecutionSignalConfig,
    RepositoryConfig,
    SignalConfig,
    SignalFieldConfig,
    SubTaskConfig,
)
from propagate_app.serve import _serve_loop, serve_command
from propagate_app.signal_transport import (
    bind_pull_socket,
    close_pull_socket,
    close_push_socket,
    connect_push_socket,
    send_signal,
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


def test_serve_receives_signal_and_runs_execution(tmp_path):
    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    address = "ipc:///tmp/propagate-test-serve-basic.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()

    executions_run = []

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase):
        executions_run.append(execution.name)

    def send_signal_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(address)
        send_signal(push, "go", {})
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_signal_then_shutdown)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    assert executions_run == ["a"]


def test_serve_continues_after_failed_run(tmp_path):
    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    address = "ipc:///tmp/propagate-test-serve-fail.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()

    call_count = 0

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise PropagateError("simulated failure")

    def send_signals_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(address)
        send_signal(push, "go", {})
        time.sleep(0.5)
        send_signal(push, "go", {})
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_signals_then_shutdown)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    assert call_count == 2


def test_serve_rejects_unknown_signal(tmp_path):
    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    address = "ipc:///tmp/propagate-test-serve-unknown.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()

    executions_run = []

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase):
        executions_run.append(execution.name)

    def send_unknown_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(address)
        send_signal(push, "unknown-signal", {})
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_unknown_then_shutdown)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    assert executions_run == []


def test_serve_rejects_invalid_payload(tmp_path):
    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(
        name="go",
        payload={"name": SignalFieldConfig(field_type="string", required=True)},
    )
    config = make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    address = "ipc:///tmp/propagate-test-serve-invalid.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()

    executions_run = []

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase):
        executions_run.append(execution.name)

    def send_invalid_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(address)
        # Missing required 'name' field
        send_signal(push, "go", {})
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_invalid_then_shutdown)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    assert executions_run == []


def test_serve_auto_resumes_on_startup(tmp_path):
    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    resume_called = []

    def mock_resume_run(config, signal_socket):
        resume_called.append(True)

    # Create a fake state file so serve_command detects it
    from propagate_app.run_state import state_file_path
    state_path = state_file_path(config.config_path)
    state_path.touch()

    def mock_serve_loop(config, signal_socket, shutdown):
        pass  # Exit immediately

    try:
        with (
            patch("propagate_app.serve._resume_run", side_effect=mock_resume_run),
            patch("propagate_app.serve._serve_loop", side_effect=mock_serve_loop),
            patch("propagate_app.serve.load_config", return_value=config),
        ):
            result = serve_command(str(config.config_path))

        assert resume_called == [True]
        assert result == 0
    finally:
        state_path.unlink(missing_ok=True)


def test_serve_passes_signal_socket_to_scheduler(tmp_path):
    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    address = "ipc:///tmp/propagate-test-serve-socket.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()

    captured_socket = []

    def mock_run_schedule(config, initial, runtime_context, run_state=None, signal_socket=None):
        captured_socket.append(signal_socket)

    def send_signal_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(address)
        send_signal(push, "go", {})
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_signal_then_shutdown)
    sender.start()

    try:
        with patch("propagate_app.serve.run_execution_schedule", side_effect=mock_run_schedule):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    assert len(captured_socket) == 1
    assert captured_socket[0] is pull


def test_serve_graceful_shutdown_via_event(tmp_path):
    exec_a = make_execution("a")
    config = make_config(tmp_path, [exec_a])

    address = "ipc:///tmp/propagate-test-serve-shutdown.sock"
    pull = bind_pull_socket(address)

    shutdown = threading.Event()
    shutdown.set()

    try:
        _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)

    # If we get here, the loop exited cleanly


def test_serve_malformed_message_ignored(tmp_path):
    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    address = "ipc:///tmp/propagate-test-serve-malformed.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()

    executions_run = []

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase):
        executions_run.append(execution.name)

    def send_malformed_then_valid_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(address)
        # Send malformed message (missing keys)
        push.send_json({"bad": "data"})
        time.sleep(0.2)
        # Send valid signal
        send_signal(push, "go", {})
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_malformed_then_valid_then_shutdown)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    # Malformed message was ignored, valid signal was processed
    assert executions_run == ["a"]


def test_serve_ambiguous_signal_logs_error_and_continues(tmp_path):
    """When multiple executions accept the same signal, the error is logged
    and the server keeps running."""
    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    exec_b = make_execution(
        "b",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a, exec_b], signals={"go": signal_cfg})

    address = "ipc:///tmp/propagate-test-serve-ambiguous.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()

    executions_run = []

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase):
        executions_run.append(execution.name)

    def send_signal_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(address)
        send_signal(push, "go", {})
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_signal_then_shutdown)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    # No execution should have run — the ambiguity error was caught
    assert executions_run == []


def test_serve_keyboard_interrupt_during_run_exits_cleanly(tmp_path):
    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    address = "ipc:///tmp/propagate-test-serve-interrupt.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase):
        raise KeyboardInterrupt

    def send_signal_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(address)
        send_signal(push, "go", {})
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_signal_then_shutdown)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    # If we get here, the loop exited cleanly instead of crashing


def test_serve_forced_shutdown_on_second_signal(tmp_path):
    """Second shutdown signal raises KeyboardInterrupt to force exit."""
    import signal as signal_module
    from propagate_app.serve import serve_command

    exec_a = make_execution(
        "a",
        signals=[ExecutionSignalConfig(signal_name="go")],
    )
    signal_cfg = SignalConfig(name="go", payload={})
    config = make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    shutdown_event = None

    def mock_serve_loop(cfg, sock, shutdown):
        nonlocal shutdown_event
        shutdown_event = shutdown
        # Simulate first signal already received
        shutdown.set()
        # Now simulate a second SIGINT hitting the handler
        handler = signal_module.getsignal(signal_module.SIGINT)
        # The second call should raise KeyboardInterrupt
        try:
            handler(signal_module.SIGINT, None)
            assert False, "Expected KeyboardInterrupt"
        except KeyboardInterrupt:
            pass

    with (
        patch("propagate_app.serve._serve_loop", side_effect=mock_serve_loop),
        patch("propagate_app.serve.load_config", return_value=config),
    ):
        result = serve_command(str(config.config_path))

    assert result == 0
