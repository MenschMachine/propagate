"""Tests for resume failure event publishing and formatting."""
from unittest.mock import MagicMock

from propagate_app.event_format import format_event_reply as _format_event_reply
from propagate_app.models import (
    AgentConfig,
    Config,
)
from propagate_app.serve import _handle_command


def _make_config(tmp_path):
    config_path = tmp_path / "propagate.yaml"
    config_path.touch()
    return Config(
        version="6",
        agent=AgentConfig(agents={"default": "echo test"}, default_agent="default"),
        repositories={},
        context_sources={},
        signals={},
        propagation_triggers=[],
        executions={},
        config_path=config_path,
    )


def test_handle_command_resume_publishes_command_failed_when_no_state(tmp_path):
    config = _make_config(tmp_path)
    pub_socket = MagicMock()
    signal_socket = MagicMock()
    metadata = {"chat_id": "123", "message_id": "456"}

    _handle_command(config, "resume", signal_socket, pub_socket=pub_socket, metadata=metadata)

    pub_socket.send_json.assert_called_once()
    event = pub_socket.send_json.call_args[0][0]
    assert event["event"] == "command_failed"
    assert event["command"] == "resume"
    assert event["message"] == "No state file found; nothing to resume."
    assert event["metadata"]["chat_id"] == "123"
    assert event["metadata"]["message_id"] == "456"


def test_handle_command_resume_no_publish_without_pub_socket(tmp_path):
    config = _make_config(tmp_path)
    signal_socket = MagicMock()

    # Should not raise when pub_socket is None
    _handle_command(config, "resume", signal_socket, pub_socket=None, metadata={"chat_id": "123"})


def test_handle_command_resume_empty_metadata_when_none(tmp_path):
    config = _make_config(tmp_path)
    pub_socket = MagicMock()
    signal_socket = MagicMock()

    _handle_command(config, "resume", signal_socket, pub_socket=pub_socket, metadata=None)

    event = pub_socket.send_json.call_args[0][0]
    assert event["metadata"] == {}


def test_format_event_reply_command_failed():
    event = {
        "event": "command_failed",
        "command": "resume",
        "message": "No state file found; nothing to resume.",
        "metadata": {"chat_id": "123"},
    }
    result = _format_event_reply(event)
    assert "resume" in result
    assert "No state file found" in result
    assert result == "Command /resume failed: No state file found; nothing to resume."


def test_format_event_reply_run_completed_unchanged():
    event = {
        "event": "run_completed",
        "signal_type": "deploy",
        "messages": ["Done."],
    }
    result = _format_event_reply(event)
    assert "completed" in result
    assert "deploy" in result
    assert "Done." in result
