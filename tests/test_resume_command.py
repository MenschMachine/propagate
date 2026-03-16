from __future__ import annotations

import logging
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from propagate_app.models import (
    AgentConfig,
    Config,
    ExecutionConfig,
    ExecutionSignalConfig,
    RepositoryConfig,
    SignalConfig,
    SubTaskConfig,
)
from propagate_app.serve import _serve_loop
from propagate_app.signal_transport import (
    bind_pull_socket,
    close_pull_socket,
    close_push_socket,
    connect_push_socket,
    receive_message,
    send_command,
    send_signal,
)

# ---------------------------------------------------------------------------
# Transport: send_command / receive_message
# ---------------------------------------------------------------------------


def test_send_command_and_receive_message():
    address = "ipc:///tmp/propagate-test-cmd-basic.sock"
    pull = bind_pull_socket(address)
    try:
        push = connect_push_socket(address)
        send_command(push, "resume")
        close_push_socket(push)

        result = receive_message(pull, block=True, timeout_ms=2000)
        assert result is not None
        kind, name, payload, _metadata = result
        assert kind == "command"
        assert name == "resume"
        assert payload == {}
    finally:
        close_pull_socket(pull, address)


def test_receive_message_returns_signal():
    address = "ipc:///tmp/propagate-test-cmd-signal.sock"
    pull = bind_pull_socket(address)
    try:
        push = connect_push_socket(address)
        send_signal(push, "deploy", {"branch": "main"})
        close_push_socket(push)

        result = receive_message(pull, block=True, timeout_ms=2000)
        assert result is not None
        kind, name, payload, _metadata = result
        assert kind == "signal"
        assert name == "deploy"
        assert payload == {"branch": "main"}
    finally:
        close_pull_socket(pull, address)


def test_receive_message_ignores_malformed():
    address = "ipc:///tmp/propagate-test-cmd-malformed.sock"
    pull = bind_pull_socket(address)
    try:
        push = connect_push_socket(address)
        push.send_json({"bad": "data"})
        close_push_socket(push)

        result = receive_message(pull, block=True, timeout_ms=2000)
        assert result is None
    finally:
        close_pull_socket(pull, address)


def test_receive_message_timeout():
    address = "ipc:///tmp/propagate-test-cmd-timeout.sock"
    pull = bind_pull_socket(address)
    try:
        result = receive_message(pull, block=True, timeout_ms=100)
        assert result is None
    finally:
        close_pull_socket(pull, address)


# ---------------------------------------------------------------------------
# Serve: _handle_command via _serve_loop
# ---------------------------------------------------------------------------


def _make_config(tmp_path, signals=None):
    config_path = tmp_path / "propagate.yaml"
    config_path.touch()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(exist_ok=True)
    exec_cfg = ExecutionConfig(
        name="a",
        repository="repo",
        depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="go")] if signals else [],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    return Config(
        version="6",
        agent=AgentConfig(command="echo test"),
        repositories={"repo": RepositoryConfig(name="repo", path=repo_dir)},
        context_sources={},
        signals=signals or {},
        propagation_triggers=[],
        executions={"a": exec_cfg},
        config_path=config_path,
    )


def test_serve_handles_resume_command_with_state_file(tmp_path):
    signal_cfg = SignalConfig(name="go", payload={})
    config = _make_config(tmp_path, signals={"go": signal_cfg})

    from propagate_app.run_state import state_file_path

    state_path = state_file_path(config.config_path)
    state_path.touch()

    address = "ipc:///tmp/propagate-test-serve-resume.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()

    resume_called = []

    def mock_resume_run(cfg, signal_socket, pub_socket=None, metadata=None):
        resume_called.append(True)

    def send_resume_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(address)
        send_command(push, "resume")
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_resume_then_shutdown)
    sender.start()

    try:
        with patch("propagate_app.serve._resume_run", side_effect=mock_resume_run):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()
        state_path.unlink(missing_ok=True)

    assert resume_called == [True]


def test_serve_handles_resume_command_without_state_file(tmp_path, caplog):
    signal_cfg = SignalConfig(name="go", payload={})
    config = _make_config(tmp_path, signals={"go": signal_cfg})

    address = "ipc:///tmp/propagate-test-serve-resume-no-state.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()

    resume_called = []

    def mock_resume_run(cfg, signal_socket, pub_socket=None, metadata=None):
        resume_called.append(True)

    def send_resume_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(address)
        send_command(push, "resume")
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_resume_then_shutdown)
    sender.start()

    try:
        with (
            patch("propagate_app.serve._resume_run", side_effect=mock_resume_run),
            caplog.at_level(logging.WARNING, logger="propagate"),
        ):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    assert resume_called == []
    assert any("nothing to resume" in r.message.lower() for r in caplog.records)


def test_serve_ignores_unknown_command(tmp_path, caplog):
    config = _make_config(tmp_path)

    address = "ipc:///tmp/propagate-test-serve-unknown-cmd.sock"
    pull = bind_pull_socket(address)
    shutdown = threading.Event()

    def send_unknown_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(address)
        send_command(push, "reboot")
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_unknown_then_shutdown)
    sender.start()

    try:
        with caplog.at_level(logging.WARNING, logger="propagate"):
            _serve_loop(config, pull, shutdown)
    finally:
        close_pull_socket(pull, address)
        sender.join()

    assert any("unknown command" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Telegram: handle_resume
# ---------------------------------------------------------------------------


def _make_update(user_id, username, text=None):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_context(push_socket, allowed_users):
    context = MagicMock()
    context.bot_data = {
        "config_signals": {},
        "push_socket": push_socket,
        "allowed_users": allowed_users,
    }
    return context


@pytest.mark.anyio
async def test_handle_resume_delivers_command():
    address = "ipc:///tmp/propagate-test-tg-resume.sock"
    pull = bind_pull_socket(address)
    try:
        push = connect_push_socket(address)
        update = _make_update(123, "michael", "/resume")
        context = _make_context(push, {123})

        from propagate_telegram.bot import handle_resume

        await handle_resume(update, context)

        update.message.reply_text.assert_called_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "resume" in reply.lower()

        result = receive_message(pull, block=True, timeout_ms=2000)
        assert result is not None
        kind, name, _, _metadata = result
        assert kind == "command"
        assert name == "resume"
    finally:
        close_push_socket(push)
        close_pull_socket(pull, address)


@pytest.mark.anyio
async def test_handle_resume_ignores_unauthorized():
    address = "ipc:///tmp/propagate-test-tg-resume-unauth.sock"
    pull = bind_pull_socket(address)
    try:
        push = connect_push_socket(address)
        update = _make_update(999, "hacker", "/resume")
        context = _make_context(push, {123})

        from propagate_telegram.bot import handle_resume

        await handle_resume(update, context)

        update.message.reply_text.assert_not_called()

        result = receive_message(pull, block=True, timeout_ms=500)
        assert result is None
    finally:
        close_push_socket(push)
        close_pull_socket(pull, address)


@pytest.mark.anyio
async def test_handle_resume_ignores_edited_message():
    from propagate_telegram.bot import handle_resume

    update = MagicMock()
    update.effective_user.id = 123
    update.effective_user.username = "michael"
    update.message = None

    push = MagicMock()
    context = _make_context(push, {123})

    await handle_resume(update, context)
    # Should not crash
