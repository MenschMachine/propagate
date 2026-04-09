import threading
import time

from propagate_app.signal_transport import (
    bind_pub_socket,
    bind_pull_socket,
    close_pub_socket,
    close_pull_socket,
    publish_event,
    receive_message,
)
from propagate_mcp import server as mcp_server


def test_ask_human_receives_matching_clarification_response(monkeypatch):
    pull_address = "ipc:///tmp/propagate-test-mcp-coordinator.sock"
    pub_address = "ipc:///tmp/propagate-test-mcp-coordinator-pub.sock"

    monkeypatch.setattr(mcp_server, "COORDINATOR_ADDRESS", pull_address)
    monkeypatch.setattr(mcp_server, "COORDINATOR_PUB_ADDRESS", pub_address)

    pull = bind_pull_socket(pull_address)
    pub = bind_pub_socket(pub_address)

    result: dict[str, str] = {}
    error: dict[str, Exception] = {}

    def _call_tool() -> None:
        try:
            result["answer"] = mcp_server.ask_human("Need input?", timeout_ms=2000)
        except Exception as exc:  # pragma: no cover - asserted below
            error["exc"] = exc

    thread = threading.Thread(target=_call_tool)
    thread.start()

    try:
        message = receive_message(pull, block=True, timeout_ms=2000)
        assert message is not None
        kind, name, payload, metadata = message
        assert kind == "coordinator"
        assert name == "event"
        assert payload["name"] == "clarification_requested"
        assert payload["payload"]["question"] == "Need input?"
        assert payload["payload"]["request_id"] == metadata["request_id"]
        assert metadata["request_id"]

        time.sleep(0.2)
        publish_event(pub, "clarification_response", {
            "request_id": metadata["request_id"],
            "answer": "Approved",
        })

        thread.join(timeout=3)
        assert not thread.is_alive()
        assert "exc" not in error
        assert result["answer"] == "Approved"
    finally:
        close_pull_socket(pull, pull_address)
        close_pub_socket(pub, pub_address)
