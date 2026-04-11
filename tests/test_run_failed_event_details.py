from __future__ import annotations

import pytest

from propagate_app.event_format import format_event_reply
from propagate_app.serve import _run_with_event_publish


class _FakePubSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def test_format_run_failed_includes_error_detail() -> None:
    event = {
        "event": "run_failed",
        "signal_type": "deploy",
        "error": "simulated failure",
    }

    result = format_event_reply(event)

    assert "Run failed for signal 'deploy'." in result
    assert "simulated failure" in result


def test_run_failed_event_includes_exception_message() -> None:
    pub_socket = _FakePubSocket()

    def raise_failure() -> None:
        raise RuntimeError("simulated failure")

    with pytest.raises(RuntimeError, match="simulated failure"):
        _run_with_event_publish(pub_socket, "deploy", {"chat_id": "42"}, raise_failure)

    assert pub_socket.sent
    event = pub_socket.sent[0]
    assert event["event"] == "run_failed"
    assert event["signal_type"] == "deploy"
    assert event["metadata"] == {"chat_id": "42"}
    assert event["error"] == "simulated failure"
