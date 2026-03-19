"""Tests for the Coordinator (coordinator/worker architecture)."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from propagate_app.coordinator import Coordinator, WorkerInfo
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
from propagate_app.signal_transport import (
    COORDINATOR_ADDRESS,
    COORDINATOR_PUB_ADDRESS,
    bind_pull_socket,
    close_pull_socket,
    close_push_socket,
    connect_push_socket,
    receive_message,
    send_coordinator_command,
)


def _make_config(tmp_path, name):
    config_path = tmp_path / f"{name}.yaml"
    config_path.touch()
    repo_dir = tmp_path / f"repo-{name}"
    repo_dir.mkdir(exist_ok=True)
    exec_cfg = ExecutionConfig(
        name=f"exec-{name}",
        repository=f"repo-{name}",
        depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="go")],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    return Config(
        version="6",
        agent=AgentConfig(command="echo test"),
        repositories={f"repo-{name}": RepositoryConfig(name=f"repo-{name}", path=repo_dir)},
        context_sources={},
        signals={"go": SignalConfig(name="go", payload={"url": SignalFieldConfig(field_type="string", required=True)})},
        propagation_triggers=[],
        executions={exec_cfg.name: exec_cfg},
        config_path=config_path,
    )


# -- signal_transport extensions -----------------------------------------------


def test_coordinator_address_constants():
    assert COORDINATOR_ADDRESS.startswith("ipc://")
    assert COORDINATOR_PUB_ADDRESS.startswith("ipc://")
    assert COORDINATOR_ADDRESS != COORDINATOR_PUB_ADDRESS


def test_send_coordinator_command():
    """send_coordinator_command sends a message with 'coordinator' key."""
    address = "ipc:///tmp/propagate-test-coord-cmd.sock"
    pull = bind_pull_socket(address)
    try:
        push = connect_push_socket(address)
        try:
            send_coordinator_command(push, "list", metadata={"request_id": "r1"})
            result = receive_message(pull, block=True, timeout_ms=2000)
            assert result is not None
            kind, name, payload, metadata = result
            assert kind == "coordinator"
            assert name == "list"
            assert metadata.get("request_id") == "r1"
        finally:
            close_push_socket(push)
    finally:
        close_pull_socket(pull, address)


def test_receive_message_coordinator():
    """receive_message recognizes coordinator messages."""
    address = "ipc:///tmp/propagate-test-coord-recv.sock"
    pull = bind_pull_socket(address)
    try:
        push = connect_push_socket(address)
        try:
            send_coordinator_command(push, "load", metadata={"request_id": "r2"}, path="/tmp/foo.yaml")
            result = receive_message(pull, block=True, timeout_ms=2000)
            assert result is not None
            kind, name, payload, metadata = result
            assert kind == "coordinator"
            assert name == "load"
            assert payload.get("path") == "/tmp/foo.yaml"
        finally:
            close_push_socket(push)
    finally:
        close_pull_socket(pull, address)


# -- Coordinator unit tests ----------------------------------------------------


def _fake_popen(ready_line="READY\n", pid=12345):
    """Create a fake Popen that simulates a worker process."""
    proc = MagicMock()
    proc.pid = pid
    proc.poll.return_value = None  # process is running
    proc.stdout.readline.return_value = ready_line
    proc.stderr.read.return_value = ""
    proc.wait.return_value = 0
    return proc


def test_coordinator_load_worker(tmp_path):
    """_load_worker spawns a process and connects sockets."""
    config = _make_config(tmp_path, "alpha")
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)

    fake_proc = _fake_popen()

    with (
        patch("propagate_app.coordinator.load_config", return_value=config),
        patch("propagate_app.coordinator.subprocess.Popen", return_value=fake_proc),
        patch("propagate_app.coordinator.connect_push_socket") as mock_push,
        patch("propagate_app.coordinator.connect_sub_socket") as mock_sub,
    ):
        mock_push.return_value = MagicMock()
        mock_sub.return_value = MagicMock()
        coordinator._load_worker(config.config_path)

    assert "alpha" in coordinator._workers
    worker = coordinator._workers["alpha"]
    assert worker.name == "alpha"
    assert worker.process is fake_proc


def test_coordinator_duplicate_project_rejected(tmp_path):
    """Loading the same project twice raises an error."""
    config = _make_config(tmp_path, "alpha")
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)

    fake_proc = _fake_popen()

    with (
        patch("propagate_app.coordinator.load_config", return_value=config),
        patch("propagate_app.coordinator.subprocess.Popen", return_value=fake_proc),
        patch("propagate_app.coordinator.connect_push_socket", return_value=MagicMock()),
        patch("propagate_app.coordinator.connect_sub_socket", return_value=MagicMock()),
    ):
        coordinator._load_worker(config.config_path)
        with pytest.raises(PropagateError, match="already loaded"):
            coordinator._load_worker(config.config_path)


def test_coordinator_stop_worker(tmp_path):
    """_stop_worker terminates the process and cleans up."""
    config = _make_config(tmp_path, "alpha")
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)

    fake_proc = _fake_popen()

    with (
        patch("propagate_app.coordinator.load_config", return_value=config),
        patch("propagate_app.coordinator.subprocess.Popen", return_value=fake_proc),
        patch("propagate_app.coordinator.connect_push_socket", return_value=MagicMock()),
        patch("propagate_app.coordinator.connect_sub_socket", return_value=MagicMock()),
        patch("propagate_app.coordinator.close_push_socket"),
        patch("propagate_app.coordinator.close_sub_socket"),
    ):
        coordinator._load_worker(config.config_path)
        assert "alpha" in coordinator._workers
        coordinator._stop_worker("alpha")

    assert "alpha" not in coordinator._workers
    fake_proc.terminate.assert_called_once()


def test_coordinator_handle_list(tmp_path):
    """_handle_list publishes a coordinator_response with project info."""
    config = _make_config(tmp_path, "alpha")
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)
    coordinator._pub_socket = MagicMock()

    fake_proc = _fake_popen()
    worker = WorkerInfo(
        name="alpha",
        config_path=config.config_path,
        process=fake_proc,
        push_socket=MagicMock(),
        sub_socket=MagicMock(),
        signals=config.signals,
    )
    coordinator._workers["alpha"] = worker

    coordinator._handle_list({"request_id": "r1"})

    coordinator._pub_socket.send_json.assert_called_once()
    msg = coordinator._pub_socket.send_json.call_args[0][0]
    assert msg["event"] == "coordinator_response"
    assert "data" in msg
    projects = msg["data"]["projects"]
    assert len(projects) == 1
    assert projects[0]["name"] == "alpha"
    assert projects[0]["status"] == "running"
    assert "go" in projects[0]["signals"]


def test_coordinator_forward_signal(tmp_path):
    """_forward_signal sends the signal to the worker's push socket."""
    config = _make_config(tmp_path, "alpha")
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)

    mock_push = MagicMock()
    worker = WorkerInfo(
        name="alpha",
        config_path=config.config_path,
        process=MagicMock(),
        push_socket=mock_push,
        sub_socket=MagicMock(),
        signals=config.signals,
    )
    coordinator._workers["alpha"] = worker

    with patch("propagate_app.coordinator.send_signal") as mock_send:
        coordinator._forward_signal("alpha", "go", {"url": "http://example.com"}, {"project": "alpha"})
        mock_send.assert_called_once_with(mock_push, "go", {"url": "http://example.com"}, metadata={"project": "alpha"})


def test_coordinator_forward_command(tmp_path):
    """_forward_command sends the command to the worker's push socket."""
    config = _make_config(tmp_path, "alpha")
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)

    mock_push = MagicMock()
    worker = WorkerInfo(
        name="alpha",
        config_path=config.config_path,
        process=MagicMock(),
        push_socket=mock_push,
        sub_socket=MagicMock(),
        signals=config.signals,
    )
    coordinator._workers["alpha"] = worker

    with patch("propagate_app.coordinator.send_command") as mock_cmd:
        coordinator._forward_command("alpha", "resume", {"project": "alpha"})
        mock_cmd.assert_called_once_with(mock_push, "resume", metadata={"project": "alpha"})


def test_coordinator_forward_unknown_project(tmp_path):
    """Forwarding to an unknown project sends an error response."""
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)
    coordinator._pub_socket = MagicMock()

    coordinator._forward_signal("nope", "go", {}, {"request_id": "r1"})

    coordinator._pub_socket.send_json.assert_called_once()
    msg = coordinator._pub_socket.send_json.call_args[0][0]
    assert "error" in msg
    assert "nope" in msg["error"]


def test_coordinator_dispatch_coordinator_list(tmp_path):
    """Dispatch routes coordinator list to _handle_list."""
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)
    coordinator._pub_socket = MagicMock()

    coordinator._dispatch("coordinator", "list", {"coordinator": "list"}, {"request_id": "r1"})
    coordinator._pub_socket.send_json.assert_called_once()


def test_coordinator_dispatch_signal(tmp_path):
    """Dispatch routes signals with project metadata to _forward_signal."""
    config = _make_config(tmp_path, "alpha")
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)

    mock_push = MagicMock()
    worker = WorkerInfo(
        name="alpha",
        config_path=config.config_path,
        process=MagicMock(),
        push_socket=mock_push,
        sub_socket=MagicMock(),
        signals=config.signals,
    )
    coordinator._workers["alpha"] = worker

    with patch("propagate_app.coordinator.send_signal") as mock_send:
        coordinator._dispatch("signal", "go", {"url": "http://example.com"}, {"project": "alpha"})
        mock_send.assert_called_once()


def test_coordinator_dispatch_signal_missing_project():
    """Signal without project in metadata returns error."""
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)
    coordinator._pub_socket = MagicMock()

    coordinator._dispatch("signal", "go", {}, {})
    coordinator._pub_socket.send_json.assert_called_once()
    msg = coordinator._pub_socket.send_json.call_args[0][0]
    assert "error" in msg


def test_coordinator_worker_not_ready(tmp_path):
    """Worker that doesn't print READY raises TimeoutError."""
    config = _make_config(tmp_path, "alpha")
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)

    fake_proc = MagicMock()
    fake_proc.stdout.readline.return_value = ""  # no output
    fake_proc.stderr.read.return_value = "some error"
    fake_proc.poll.return_value = 1
    fake_proc.wait.return_value = 1

    with (
        patch("propagate_app.coordinator.load_config", return_value=config),
        patch("propagate_app.coordinator.subprocess.Popen", return_value=fake_proc),
    ):
        with pytest.raises(TimeoutError, match="failed to start"):
            coordinator._load_worker(config.config_path)


def test_coordinator_health_check_detects_dead_worker(tmp_path):
    """Health check detects when a worker process dies."""
    config = _make_config(tmp_path, "alpha")
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)
    coordinator._pub_socket = MagicMock()

    fake_proc = MagicMock()
    fake_proc.poll.return_value = 1  # process exited
    fake_proc.wait.return_value = 1

    worker = WorkerInfo(
        name="alpha",
        config_path=config.config_path,
        process=fake_proc,
        push_socket=MagicMock(),
        sub_socket=MagicMock(),
        signals=config.signals,
    )
    coordinator._workers["alpha"] = worker

    with (
        patch("propagate_app.coordinator.close_push_socket"),
        patch("propagate_app.coordinator.close_sub_socket"),
    ):
        # Run one health check iteration manually.
        with coordinator._lock:
            dead = [
                name for name, w in coordinator._workers.items()
                if w.process.poll() is not None
            ]
        for name in dead:
            coordinator._stop_worker(name)

    assert "alpha" not in coordinator._workers


def test_coordinator_handle_unload(tmp_path):
    """_handle_unload stops a worker and responds."""
    config = _make_config(tmp_path, "alpha")
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)
    coordinator._pub_socket = MagicMock()

    fake_proc = _fake_popen()
    worker = WorkerInfo(
        name="alpha",
        config_path=config.config_path,
        process=fake_proc,
        push_socket=MagicMock(),
        sub_socket=MagicMock(),
        signals=config.signals,
    )
    coordinator._workers["alpha"] = worker

    with (
        patch("propagate_app.coordinator.close_push_socket"),
        patch("propagate_app.coordinator.close_sub_socket"),
    ):
        coordinator._handle_unload("alpha", {"request_id": "r1"})

    assert "alpha" not in coordinator._workers
    calls = coordinator._pub_socket.send_json.call_args_list
    # Should have a response with "unloaded"
    response_msgs = [c[0][0] for c in calls]
    assert any("unloaded" in str(m.get("data", {})) for m in response_msgs)


def test_coordinator_handle_unload_unknown():
    """Unloading a non-existent project returns error."""
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)
    coordinator._pub_socket = MagicMock()

    coordinator._handle_unload("nope", {"request_id": "r1"})
    msg = coordinator._pub_socket.send_json.call_args[0][0]
    assert "error" in msg
    assert "nope" in msg["error"]


def test_coordinator_handle_reload(tmp_path):
    """_handle_reload stops and restarts a worker."""
    config = _make_config(tmp_path, "alpha")
    shutdown = threading.Event()
    coordinator = Coordinator(shutdown)
    coordinator._pub_socket = MagicMock()

    fake_proc = _fake_popen()
    worker = WorkerInfo(
        name="alpha",
        config_path=config.config_path,
        process=fake_proc,
        push_socket=MagicMock(),
        sub_socket=MagicMock(),
        signals=config.signals,
    )
    coordinator._workers["alpha"] = worker

    new_proc = _fake_popen(pid=99999)

    with (
        patch("propagate_app.coordinator.close_push_socket"),
        patch("propagate_app.coordinator.close_sub_socket"),
        patch("propagate_app.coordinator.load_config", return_value=config),
        patch("propagate_app.coordinator.subprocess.Popen", return_value=new_proc),
        patch("propagate_app.coordinator.connect_push_socket", return_value=MagicMock()),
        patch("propagate_app.coordinator.connect_sub_socket", return_value=MagicMock()),
    ):
        coordinator._handle_reload("alpha", {"request_id": "r1"})

    assert "alpha" in coordinator._workers
    assert coordinator._workers["alpha"].process is new_proc
