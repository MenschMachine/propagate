import time

import yaml

from propagate_app.cli import main
from propagate_app.signal_transport import bind_pull_socket, close_pull_socket, receive_signal


def write_config(tmp_path, signals=None, executions=None, propagation=None):
    config = {
        "version": "6",
        "agent": {"command": "echo {prompt_file}"},
        "repositories": {"repo": {"path": str(tmp_path / "repo")}},
    }
    (tmp_path / "repo").mkdir(exist_ok=True)
    if signals:
        config["signals"] = signals
    if executions:
        config["executions"] = executions
    else:
        config["executions"] = {
            "default": {
                "repository": "repo",
                "sub_tasks": [{"id": "t1"}],
            }
        }
    if propagation:
        config["propagation"] = propagation
    config_path = tmp_path / "propagate.yaml"
    config_path.write_text(yaml.dump(config))
    return config_path


def test_send_signal_delivers_to_pull_socket(tmp_path):
    config_path = write_config(
        tmp_path,
        signals={"deploy": {"payload": {"env": {"type": "string", "required": True}}}},
    )

    from propagate_app.signal_transport import socket_address
    address = socket_address(config_path)
    pull = bind_pull_socket(address)

    try:
        result = main([
            "send-signal",
            "--config", str(config_path),
            "--signal", "deploy",
            "--signal-payload", "{env: production}",
        ])
        assert result == 0

        time.sleep(0.05)
        msg = receive_signal(pull, block=True, timeout_ms=2000)
        assert msg is not None
        signal_type, payload = msg
        assert signal_type == "deploy"
        assert payload == {"env": "production"}
    finally:
        close_pull_socket(pull, address)


def test_send_signal_validates_unknown_signal(tmp_path):
    config_path = write_config(tmp_path)

    result = main([
        "send-signal",
        "--config", str(config_path),
        "--signal", "nonexistent",
    ])
    assert result == 1


def test_send_signal_validates_payload(tmp_path):
    config_path = write_config(
        tmp_path,
        signals={"deploy": {"payload": {"env": {"type": "string", "required": True}}}},
    )

    # Missing required field
    result = main([
        "send-signal",
        "--config", str(config_path),
        "--signal", "deploy",
        "--signal-payload", "{}",
    ])
    assert result == 1


def test_send_signal_with_signal_file(tmp_path):
    config_path = write_config(
        tmp_path,
        signals={"deploy": {"payload": {"env": {"type": "string", "required": True}}}},
    )

    signal_file = tmp_path / "signal.yaml"
    signal_file.write_text(yaml.dump({"type": "deploy", "payload": {"env": "staging"}}))

    from propagate_app.signal_transport import socket_address
    address = socket_address(config_path)
    pull = bind_pull_socket(address)

    try:
        result = main([
            "send-signal",
            "--config", str(config_path),
            "--signal-file", str(signal_file),
        ])
        assert result == 0

        time.sleep(0.05)
        msg = receive_signal(pull, block=True, timeout_ms=2000)
        assert msg is not None
        assert msg[0] == "deploy"
        assert msg[1] == {"env": "staging"}
    finally:
        close_pull_socket(pull, address)
