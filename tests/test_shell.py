from __future__ import annotations

import collections
import queue
from unittest.mock import MagicMock, patch

from propagate_app.models import SignalConfig, SignalFieldConfig
from propagate_app.shell import (
    _QUIT,
    _cmd_help,
    _cmd_logs,
    _cmd_resume,
    _cmd_signal,
    _cmd_signals,
    _dispatch,
    _event_listener,
    _ShellState,
)


def _make_state(signals=None):
    """Create a _ShellState with a single project containing the given signals."""
    state = _ShellState()
    signals_info = {}
    if signals:
        for name, sig in signals.items():
            fields = {}
            for fname, fcfg in sig.payload.items():
                fields[fname] = {"field_type": fcfg.field_type, "required": fcfg.required}
            signals_info[name] = {"payload": fields}
    state.projects = {"default": {"name": "default", "signals": signals_info}}
    state.active_project = "default"
    return state


def _signal_config(name, fields):
    payload = {}
    for fname, ftype, required in fields:
        payload[fname] = SignalFieldConfig(field_type=ftype, required=required)
    return SignalConfig(name=name, payload=payload)


# -- /signal ------------------------------------------------------------------

def test_dispatch_signal():
    sig = _signal_config("deploy", [("url", "string", True)])
    state = _make_state({"deploy": sig})
    push = MagicMock()

    with patch("propagate_app.shell.send_signal") as mock_send:
        _cmd_signal("deploy url:http://example.com", push, state)
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][1] == "deploy"
        assert args[0][2] == {"url": "http://example.com"}


def test_dispatch_signal_unknown(capsys):
    state = _make_state({"deploy": _signal_config("deploy", [])})
    push = MagicMock()

    _cmd_signal("unknown", push, state)
    out = capsys.readouterr().out
    assert "not defined" in out


def test_dispatch_signal_missing_required(capsys):
    sig = _signal_config("deploy", [("url", "string", True)])
    state = _make_state({"deploy": sig})
    push = MagicMock()

    _cmd_signal("deploy", push, state)
    out = capsys.readouterr().out
    assert "Missing required field(s): url" in out


def test_dispatch_signal_empty(capsys):
    state = _make_state({})
    push = MagicMock()

    _cmd_signal("", push, state)
    out = capsys.readouterr().out
    assert "Usage:" in out


def test_dispatch_signal_injects_sender():
    sig = _signal_config("deploy", [("sender", "string", False), ("url", "string", True)])
    state = _make_state({"deploy": sig})
    push = MagicMock()

    with patch("propagate_app.shell.send_signal") as mock_send, \
         patch("propagate_app.shell.getpass") as mock_getpass:
        mock_getpass.getuser.return_value = "testuser"
        _cmd_signal("deploy url:http://example.com", push, state)
        payload = mock_send.call_args[0][2]
        assert payload["sender"] == "testuser"


# -- /resume -------------------------------------------------------------------

def test_dispatch_resume():
    state = _make_state({})
    push = MagicMock()
    with patch("propagate_app.shell.send_command") as mock_cmd:
        _cmd_resume(push, state)
        mock_cmd.assert_called_once()


# -- /signals ------------------------------------------------------------------

def test_dispatch_signals_list(capsys):
    sig = _signal_config("deploy", [("url", "string", True), ("env", "string", False)])
    state = _make_state({"deploy": sig})

    _cmd_signals(state)
    out = capsys.readouterr().out
    assert "deploy" in out
    assert "url" in out
    assert "required" in out
    assert "env" in out


def test_dispatch_signals_empty(capsys):
    state = _make_state({})
    _cmd_signals(state)
    out = capsys.readouterr().out
    assert "No signals configured" in out


# -- /logs ---------------------------------------------------------------------

def test_dispatch_logs(capsys):
    buf = collections.deque(maxlen=500)
    buf.extend(["line1", "line2", "line3"])

    _cmd_logs("2", buf)
    out = capsys.readouterr().out
    assert "line2" in out
    assert "line3" in out


def test_dispatch_logs_empty(capsys):
    buf = collections.deque(maxlen=500)
    _cmd_logs("", buf)
    out = capsys.readouterr().out
    assert "No logs available" in out


def test_dispatch_logs_bad_number(capsys):
    buf = collections.deque(maxlen=500)
    _cmd_logs("abc", buf)
    out = capsys.readouterr().out
    assert "must be a number" in out


# -- /help ---------------------------------------------------------------------

def test_dispatch_help(capsys):
    _cmd_help()
    out = capsys.readouterr().out
    assert "/signal" in out
    assert "/resume" in out
    assert "/signals" in out
    assert "/logs" in out
    assert "/help" in out
    assert "/quit" in out
    assert "/list" in out
    assert "/load" in out


# -- dispatch routing ----------------------------------------------------------

def test_dispatch_unknown_command(capsys):
    state = _make_state({})
    push = MagicMock()
    buf = collections.deque(maxlen=500)
    _dispatch("/foo", push, buf, state)
    out = capsys.readouterr().out
    assert "Unknown command" in out


def test_dispatch_quit_returns_sentinel():
    state = _make_state({})
    push = MagicMock()
    buf = collections.deque(maxlen=500)
    assert _dispatch("/quit", push, buf, state) is _QUIT


def test_dispatch_exit_returns_sentinel():
    state = _make_state({})
    push = MagicMock()
    buf = collections.deque(maxlen=500)
    assert _dispatch("/exit", push, buf, state) is _QUIT


# -- event listener ------------------------------------------------------------

def test_event_listener_log_buffered():
    log_buffer = collections.deque(maxlen=500)
    stop = MagicMock()
    stop.is_set = MagicMock(side_effect=[False, True])
    response_queue = queue.Queue()

    with patch("propagate_app.shell.receive_event") as mock_recv:
        mock_recv.return_value = {"event": "log", "line": "hello"}
        _event_listener(MagicMock(), log_buffer, stop, response_queue)

    assert "hello" in list(log_buffer)


def test_event_listener_formatted():
    log_buffer = collections.deque(maxlen=500)
    stop = MagicMock()
    stop.is_set = MagicMock(side_effect=[False, True])
    response_queue = queue.Queue()

    event = {"event": "run_completed", "signal_type": "deploy"}

    with (
        patch("propagate_app.shell.receive_event", return_value=event),
        patch("propagate_app.shell._print_event") as mock_print,
    ):
        _event_listener(MagicMock(), log_buffer, stop, response_queue)
        mock_print.assert_called_once()
        assert "Run completed" in mock_print.call_args[0][0]


def test_event_listener_coordinator_response_queued():
    log_buffer = collections.deque(maxlen=500)
    stop = MagicMock()
    stop.is_set = MagicMock(side_effect=[False, True])
    response_queue = queue.Queue()

    event = {"event": "coordinator_response", "request_id": "r1", "data": {}}

    with patch("propagate_app.shell.receive_event", return_value=event):
        _event_listener(MagicMock(), log_buffer, stop, response_queue)

    assert not response_queue.empty()
    assert response_queue.get()["request_id"] == "r1"
