from pathlib import Path

from propagate_app.signal_transport import (
    bind_pull_socket,
    close_pull_socket,
    close_push_socket,
    connect_push_socket,
    receive_signal,
    send_signal,
    socket_address,
)


def test_socket_address_from_config_path(tmp_path):
    config_path = tmp_path / "my-config.yaml"
    config_path.touch()
    address = socket_address(config_path)
    assert address.startswith("ipc:///tmp/propagate-")
    assert address.endswith(".sock")


def test_socket_address_differs_for_same_filename_different_dirs(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    config_a = dir_a / "propagate.yaml"
    config_b = dir_b / "propagate.yaml"
    config_a.touch()
    config_b.touch()
    assert socket_address(config_a) != socket_address(config_b)


def test_send_receive_round_trip():
    address = "ipc:///tmp/propagate-test-roundtrip.sock"
    pull = bind_pull_socket(address)
    push = connect_push_socket(address)
    try:
        send_signal(push, "pr-labeled", {"label": "approved", "pr": 42})
        result = receive_signal(pull, block=True, timeout_ms=2000)
        assert result is not None
        signal_type, payload = result
        assert signal_type == "pr-labeled"
        assert payload == {"label": "approved", "pr": 42}
    finally:
        close_push_socket(push)
        close_pull_socket(pull, address)


def test_nonblocking_receive_returns_none_when_empty():
    address = "ipc:///tmp/propagate-test-nonblock.sock"
    pull = bind_pull_socket(address)
    try:
        result = receive_signal(pull, block=False)
        assert result is None
    finally:
        close_pull_socket(pull, address)


def test_blocking_receive_returns_none_on_timeout():
    address = "ipc:///tmp/propagate-test-timeout.sock"
    pull = bind_pull_socket(address)
    try:
        result = receive_signal(pull, block=True, timeout_ms=100)
        assert result is None
    finally:
        close_pull_socket(pull, address)


def test_multiple_signals_received_in_order():
    address = "ipc:///tmp/propagate-test-order.sock"
    pull = bind_pull_socket(address)
    push = connect_push_socket(address)
    try:
        send_signal(push, "signal-a", {"n": 1})
        send_signal(push, "signal-b", {"n": 2})
        send_signal(push, "signal-c", {"n": 3})

        results = []
        for _ in range(3):
            result = receive_signal(pull, block=True, timeout_ms=2000)
            assert result is not None
            results.append(result)

        assert results[0] == ("signal-a", {"n": 1})
        assert results[1] == ("signal-b", {"n": 2})
        assert results[2] == ("signal-c", {"n": 3})
    finally:
        close_push_socket(push)
        close_pull_socket(pull, address)


def test_receive_signal_ignores_non_json_bytes():
    import time

    address = "ipc:///tmp/propagate-test-raw-bytes.sock"
    pull = bind_pull_socket(address)
    push = connect_push_socket(address)
    try:
        # Send raw bytes that aren't valid JSON
        push.send(b"\x80\x81\x82 not json")
        time.sleep(0.05)
        result = receive_signal(pull, block=True, timeout_ms=2000)
        assert result is None
        # Socket still works for valid messages after
        send_signal(push, "test", {})
        result = receive_signal(pull, block=True, timeout_ms=2000)
        assert result == ("test", {})
    finally:
        close_push_socket(push)
        close_pull_socket(pull, address)


def test_stale_socket_file_cleaned_on_bind(tmp_path):
    address = "ipc:///tmp/propagate-test-stale.sock"
    # Create a stale file
    Path("/tmp/propagate-test-stale.sock").touch()
    pull = bind_pull_socket(address)
    try:
        push = connect_push_socket(address)
        send_signal(push, "test", {})
        result = receive_signal(pull, block=True, timeout_ms=2000)
        assert result == ("test", {})
        close_push_socket(push)
    finally:
        close_pull_socket(pull, address)
