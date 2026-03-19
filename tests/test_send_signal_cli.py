import time

import yaml

from propagate_app.cli import main
from propagate_app.signal_transport import (
    COORDINATOR_ADDRESS,
    bind_pull_socket,
    close_pull_socket,
    receive_message,
)


def test_send_signal_delivers_to_coordinator():
    """send-signal --project routes the signal through the coordinator PULL socket."""
    pull = bind_pull_socket(COORDINATOR_ADDRESS)
    try:
        result = main([
            "send-signal",
            "--project", "my-project",
            "--signal", "deploy",
            "--signal-payload", "{env: production}",
        ])
        assert result == 0

        time.sleep(0.05)
        msg = receive_message(pull, block=True, timeout_ms=2000)
        assert msg is not None
        kind, name, payload, metadata = msg
        assert kind == "signal"
        assert name == "deploy"
        assert payload == {"env": "production"}
        assert metadata["project"] == "my-project"
    finally:
        close_pull_socket(pull, COORDINATOR_ADDRESS)


def test_send_signal_with_signal_file(tmp_path):
    """send-signal --signal-file sends the signal from a YAML file."""
    signal_file = tmp_path / "signal.yaml"
    signal_file.write_text(yaml.dump({"type": "deploy", "payload": {"env": "staging"}}))

    pull = bind_pull_socket(COORDINATOR_ADDRESS)
    try:
        result = main([
            "send-signal",
            "--project", "my-project",
            "--signal-file", str(signal_file),
        ])
        assert result == 0

        time.sleep(0.05)
        msg = receive_message(pull, block=True, timeout_ms=2000)
        assert msg is not None
        kind, name, payload, metadata = msg
        assert kind == "signal"
        assert name == "deploy"
        assert payload == {"env": "staging"}
    finally:
        close_pull_socket(pull, COORDINATOR_ADDRESS)


def test_send_signal_requires_project():
    """send-signal without --project fails."""
    try:
        main(["send-signal", "--signal", "deploy"])
        assert False, "Should have exited"
    except SystemExit as exc:
        assert exc.code == 2  # argparse error
