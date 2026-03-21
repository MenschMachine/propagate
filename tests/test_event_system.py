from __future__ import annotations

import asyncio
import logging
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from propagate_app.errors import PropagateError
from propagate_app.models import (
    AgentConfig,
    Config,
    ExecutionConfig,
    ExecutionScheduleState,
    ExecutionSignalConfig,
    RepositoryConfig,
    RunState,
    SignalConfig,
    SignalFieldConfig,
    SubTaskConfig,
)
from propagate_app.processes import run_agent_command
from propagate_app.serve import _RunLogBuffer, _serve_loop
from propagate_app.signal_transport import (
    bind_pub_socket,
    bind_pull_socket,
    close_pub_socket,
    close_pull_socket,
    close_push_socket,
    close_sub_socket,
    connect_push_socket,
    connect_sub_socket,
    publish_event,
    receive_event,
    receive_message,
    send_signal,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path, executions, signals=None):
    config_path = tmp_path / "propagate.yaml"
    config_path.touch()
    repos = {}
    for e in executions:
        if e.repository not in repos:
            repo_dir = tmp_path / e.repository
            repo_dir.mkdir(exist_ok=True)
            repos[e.repository] = RepositoryConfig(name=e.repository, path=repo_dir)
    return Config(
        version="6",
        agent=AgentConfig(command="echo test"),
        repositories=repos,
        context_sources={},
        signals=signals or {},
        propagation_triggers=[],
        executions={e.name: e for e in executions},
        config_path=config_path,
    )


def _make_execution(name, signals=None):
    return ExecutionConfig(
        name=name,
        repository="repo",
        depends_on=[],
        signals=signals or [],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )


# ---------------------------------------------------------------------------
# Metadata flows through ZMQ without touching signal validation
# ---------------------------------------------------------------------------


def test_metadata_flows_through_zmq_message():
    address = "ipc:///tmp/propagate-test-metadata-flow.sock"
    pull = bind_pull_socket(address)
    try:
        push = connect_push_socket(address)
        try:
            send_signal(push, "deploy", {"env": "prod"}, metadata={"chat_id": "123", "message_id": "456"})
            result = receive_message(pull, block=True, timeout_ms=2000)
            assert result is not None
            kind, name, payload, metadata = result
            assert kind == "signal"
            assert name == "deploy"
            assert payload == {"env": "prod"}
            assert metadata == {"chat_id": "123", "message_id": "456"}
        finally:
            close_push_socket(push)
    finally:
        close_pull_socket(pull, address)


def test_metadata_absent_returns_empty_dict():
    address = "ipc:///tmp/propagate-test-metadata-absent.sock"
    pull = bind_pull_socket(address)
    try:
        push = connect_push_socket(address)
        try:
            send_signal(push, "deploy", {})
            result = receive_message(pull, block=True, timeout_ms=2000)
            assert result is not None
            _, _, _, metadata = result
            assert metadata == {}
        finally:
            close_push_socket(push)
    finally:
        close_pull_socket(pull, address)


def test_command_message_returns_metadata():
    address = "ipc:///tmp/propagate-test-cmd-metadata.sock"
    pull = bind_pull_socket(address)
    try:
        push = connect_push_socket(address)
        try:
            push.send_json({"command": "resume", "metadata": {"chat_id": "99"}})
            result = receive_message(pull, block=True, timeout_ms=2000)
            assert result is not None
            kind, name, payload, metadata = result
            assert kind == "command"
            assert name == "resume"
            assert metadata == {"chat_id": "99"}
        finally:
            close_push_socket(push)
    finally:
        close_pull_socket(pull, address)


# ---------------------------------------------------------------------------
# Agent stdout capture and logging
# ---------------------------------------------------------------------------


def test_agent_command_captures_stdout(tmp_path):
    """run_agent_command logs stdout lines via LOGGER.info."""
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture()
    logger = logging.getLogger("propagate")
    prev_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        run_agent_command("echo hello-from-agent", tmp_path, "t1")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)

    assert any("hello-from-agent" in r for r in records)


def test_agent_command_raises_on_failure(tmp_path):
    with pytest.raises(PropagateError, match="exit code"):
        run_agent_command("exit 1", tmp_path, "t1")


# ---------------------------------------------------------------------------
# PUB/SUB event publishing and receiving
# ---------------------------------------------------------------------------


def test_pub_sub_event_roundtrip():
    address = "ipc:///tmp/propagate-test-pubsub.sock"
    pub = bind_pub_socket(address)
    try:
        sub = connect_sub_socket(address)
        try:
            # PUB/SUB needs a brief settle time
            time.sleep(0.1)
            publish_event(pub, "run_completed", {
                "signal_type": "deploy",
                "metadata": {"chat_id": "42"},
                "messages": ["msg1", "msg2"],
            })
            event = receive_event(sub, timeout_ms=2000)
            assert event is not None
            assert event["event"] == "run_completed"
            assert event["signal_type"] == "deploy"
            assert event["metadata"] == {"chat_id": "42"}
            assert event["messages"] == ["msg1", "msg2"]
        finally:
            close_sub_socket(sub)
    finally:
        close_pub_socket(pub, address)


def test_receive_event_returns_none_on_timeout():
    address = "ipc:///tmp/propagate-test-pubsub-timeout.sock"
    pub = bind_pub_socket(address)
    try:
        sub = connect_sub_socket(address)
        try:
            time.sleep(0.1)
            event = receive_event(sub, timeout_ms=100)
            assert event is None
        finally:
            close_sub_socket(sub)
    finally:
        close_pub_socket(pub, address)


# ---------------------------------------------------------------------------
# _RunLogBuffer
# ---------------------------------------------------------------------------


def test_run_log_buffer_captures_last_n():
    buffer = _RunLogBuffer(maxlen=3)
    buffer.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("propagate.test.buffer")
    logger.addHandler(buffer)
    logger.setLevel(logging.DEBUG)
    try:
        for i in range(5):
            logger.info("message %d", i)
    finally:
        logger.removeHandler(buffer)

    msgs = buffer.messages()
    assert len(msgs) == 3
    assert msgs == ["message 2", "message 3", "message 4"]


def test_run_log_buffer_empty():
    buffer = _RunLogBuffer(maxlen=3)
    assert buffer.messages() == []


# ---------------------------------------------------------------------------
# Serve publishes event on run completion and failure
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_serve_publishes_event_on_completion(tmp_path):
    exec_a = _make_execution("a", signals=[ExecutionSignalConfig(signal_name="go")])
    signal_cfg = SignalConfig(name="go", payload={})
    config = _make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    pull_address = "ipc:///tmp/propagate-test-serve-pub-ok.sock"
    pub_address = "ipc:///tmp/propagate-test-serve-pub-ok-events.sock"

    pull = bind_pull_socket(pull_address)
    pub = bind_pub_socket(pub_address)
    sub = connect_sub_socket(pub_address)
    time.sleep(0.1)

    shutdown = threading.Event()

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase, on_runtime_context_updated=None, on_tasks_reset=None):
        return runtime_context

    def send_signal_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(pull_address)
        send_signal(push, "go", {}, metadata={"chat_id": "100"})
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_signal_then_shutdown)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            _serve_loop(config, pull, shutdown, pub)
    finally:
        close_pull_socket(pull, pull_address)
        sender.join()

    event = receive_event(sub, timeout_ms=2000)
    close_sub_socket(sub)
    close_pub_socket(pub, pub_address)

    assert event is not None
    assert event["event"] == "run_completed"
    assert event["signal_type"] == "go"
    assert event["metadata"] == {"chat_id": "100"}
    assert isinstance(event["messages"], list)


@pytest.mark.slow
def test_serve_publishes_event_on_failure(tmp_path):
    exec_a = _make_execution("a", signals=[ExecutionSignalConfig(signal_name="go")])
    signal_cfg = SignalConfig(name="go", payload={})
    config = _make_config(tmp_path, [exec_a], signals={"go": signal_cfg})

    pull_address = "ipc:///tmp/propagate-test-serve-pub-fail.sock"
    pub_address = "ipc:///tmp/propagate-test-serve-pub-fail-events.sock"

    pull = bind_pull_socket(pull_address)
    pub = bind_pub_socket(pub_address)
    sub = connect_sub_socket(pub_address)
    time.sleep(0.1)

    shutdown = threading.Event()

    def mock_run_execution(execution, runtime_context, completed_task_phases, on_phase_completed, completed_execution_phase, on_runtime_context_updated=None, on_tasks_reset=None):
        raise PropagateError("simulated failure")

    def send_signal_then_shutdown():
        time.sleep(0.3)
        push = connect_push_socket(pull_address)
        send_signal(push, "go", {}, metadata={"chat_id": "200"})
        close_push_socket(push)
        time.sleep(0.5)
        shutdown.set()

    sender = threading.Thread(target=send_signal_then_shutdown)
    sender.start()

    try:
        with patch("propagate_app.scheduler.run_configured_execution", side_effect=mock_run_execution):
            _serve_loop(config, pull, shutdown, pub)
    finally:
        close_pull_socket(pull, pull_address)
        sender.join()

    event = receive_event(sub, timeout_ms=2000)
    close_sub_socket(sub)
    close_pub_socket(pub, pub_address)

    assert event is not None
    assert event["event"] == "run_failed"
    assert event["signal_type"] == "go"
    assert event["metadata"] == {"chat_id": "200"}


# ---------------------------------------------------------------------------
# Telegram bot sends metadata with signal
# ---------------------------------------------------------------------------


@pytest.fixture
def zmq_pair():
    address = "ipc:///tmp/propagate-test-tg-reply.sock"
    pull = bind_pull_socket(address)
    push = connect_push_socket(address)
    yield pull, push, address
    close_push_socket(push)
    close_pull_socket(pull, address)


def _make_update(user_id, username, text, chat_id=111, message_id=222):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.message_id = message_id
    update.message.reply_text = AsyncMock()
    return update


def _make_context(config_signals, push_socket, allowed_users):
    from propagate_telegram.bot import ProjectState

    project = ProjectState(name="default", config_signals=config_signals)
    context = MagicMock()
    context.bot_data = {
        "projects": {"default": project},
        "active_project": {},
        "allowed_users": allowed_users,
        "push_socket": push_socket,
    }
    return context


SIGNALS = {
    "deploy": SignalConfig(
        name="deploy",
        payload={
            "instructions": SignalFieldConfig(field_type="string", required=False),
            "sender": SignalFieldConfig(field_type="string", required=False),
        },
    ),
}


@pytest.mark.anyio
async def test_handle_signal_sends_metadata(zmq_pair):
    from propagate_telegram.bot import handle_signal

    pull, push, _ = zmq_pair
    update = _make_update(123, "michael", "/signal deploy\nDo it.", chat_id=777, message_id=888)
    context = _make_context(SIGNALS, push, {123})

    await handle_signal(update, context)

    result = receive_message(pull, block=True, timeout_ms=2000)
    assert result is not None
    kind, name, payload, metadata = result
    assert kind == "signal"
    assert name == "deploy"
    assert metadata["chat_id"] == "777"
    assert metadata["message_id"] == "888"


# ---------------------------------------------------------------------------
# Telegram bot event reply formatting
# ---------------------------------------------------------------------------


def test_format_event_reply_completed():
    from propagate_app.event_format import format_event_reply as _format_event_reply

    reply = _format_event_reply({
        "event": "run_completed",
        "signal_type": "deploy",
        "messages": ["Setting up...", "Running agent...", "Done."],
    })
    assert "completed" in reply
    assert "deploy" in reply
    assert "Done." in reply


def test_format_event_reply_failed():
    from propagate_app.event_format import format_event_reply as _format_event_reply

    reply = _format_event_reply({
        "event": "run_failed",
        "signal_type": "deploy",
        "messages": ["Starting...", "Error occurred."],
    })
    assert "failed" in reply
    assert "deploy" in reply
    assert "Error occurred." in reply


def test_format_event_reply_no_messages():
    from propagate_app.event_format import format_event_reply as _format_event_reply

    reply = _format_event_reply({
        "event": "run_completed",
        "signal_type": "deploy",
        "messages": [],
    })
    assert "completed" in reply
    assert "deploy" in reply


# ---------------------------------------------------------------------------
# RunState metadata persistence
# ---------------------------------------------------------------------------


def test_run_state_metadata_persistence(tmp_path):
    from propagate_app.run_state import load_run_state, save_run_state

    config_path = tmp_path / "propagate.yaml"
    config_path.touch()

    state = RunState(
        config_path=config_path,
        initial_execution="a",
        schedule=ExecutionScheduleState(active_names=set(), completed_names=set()),
        active_signal=None,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
        metadata={"chat_id": "42", "message_id": "99"},
    )
    save_run_state(state)
    loaded = load_run_state(config_path)
    assert loaded.metadata == {"chat_id": "42", "message_id": "99"}


def test_run_state_metadata_default_empty(tmp_path):
    from propagate_app.run_state import load_run_state, save_run_state

    config_path = tmp_path / "propagate.yaml"
    config_path.touch()

    state = RunState(
        config_path=config_path,
        initial_execution="a",
        schedule=ExecutionScheduleState(active_names=set(), completed_names=set()),
        active_signal=None,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
    )
    save_run_state(state)
    loaded = load_run_state(config_path)
    assert loaded.metadata == {}


# ---------------------------------------------------------------------------
# handle_resume sends metadata
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handle_resume_sends_metadata(zmq_pair):
    from propagate_telegram.bot import handle_resume

    pull, push, _ = zmq_pair
    update = _make_update(123, "michael", "/resume", chat_id=555, message_id=666)
    context = _make_context(SIGNALS, push, {123})

    await handle_resume(update, context)

    result = receive_message(pull, block=True, timeout_ms=2000)
    assert result is not None
    kind, name, _payload, metadata = result
    assert kind == "command"
    assert name == "resume"
    assert metadata["chat_id"] == "555"
    assert metadata["message_id"] == "666"


# ---------------------------------------------------------------------------
# _poll_events integration
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_poll_events_sends_reply():
    """_poll_events reads an event from SUB and calls bot.send_message."""
    from propagate_telegram.bot import _poll_events

    pub_address = "ipc:///tmp/propagate-test-poll-events.sock"
    pub = bind_pub_socket(pub_address)
    sub = connect_sub_socket(pub_address)
    time.sleep(0.1)

    application = MagicMock()
    application.bot.send_message = AsyncMock()
    application.bot_data = {"response_queue": asyncio.Queue()}

    task = asyncio.create_task(_poll_events(application, sub))

    # Publish an event with metadata
    publish_event(pub, "run_completed", {
        "signal_type": "deploy",
        "metadata": {"chat_id": "42", "message_id": "7"},
        "messages": ["All done."],
    })

    # Give the poll loop time to receive and process
    await asyncio.sleep(0.5)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    close_sub_socket(sub)
    close_pub_socket(pub, pub_address)

    application.bot.send_message.assert_called_once()
    call_kwargs = application.bot.send_message.call_args[1]
    assert call_kwargs["chat_id"] == 42
    assert call_kwargs["reply_to_message_id"] == 7
    assert "completed" in call_kwargs["text"]
    assert "All done." in call_kwargs["text"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_poll_events_skips_event_without_chat_id():
    """Events without chat_id in metadata are skipped — no send_message call."""
    from propagate_telegram.bot import _poll_events

    pub_address = "ipc:///tmp/propagate-test-poll-no-chat.sock"
    pub = bind_pub_socket(pub_address)
    sub = connect_sub_socket(pub_address)
    time.sleep(0.1)

    application = MagicMock()
    application.bot.send_message = AsyncMock()
    application.bot_data = {"response_queue": asyncio.Queue()}

    task = asyncio.create_task(_poll_events(application, sub))

    publish_event(pub, "run_completed", {
        "signal_type": "deploy",
        "metadata": {},
        "messages": ["Done."],
    })

    await asyncio.sleep(0.5)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    close_sub_socket(sub)
    close_pub_socket(pub, pub_address)

    application.bot.send_message.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_poll_events_sends_pr_created_to_notify_chats():
    """pr_created without chat metadata is sent to configured notify chats."""
    import asyncio

    from propagate_telegram.bot import _poll_events

    fake_event = {
        "event": "pr_created",
        "execution": "deploy",
        "pr_url": "https://github.com/org/repo/pull/7",
        "metadata": {},
    }
    call_count = 0

    def fake_receive(sub_socket, timeout_ms=1000):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fake_event
        raise asyncio.CancelledError

    application = MagicMock()
    application.bot.send_message = AsyncMock()
    application.bot_data = {
        "notify_chats": {42, 99},
        "response_queue": asyncio.Queue(),
    }

    with patch("propagate_telegram.bot.receive_event", side_effect=fake_receive):
        try:
            await _poll_events(application, MagicMock())
        except asyncio.CancelledError:
            pass

    assert application.bot.send_message.await_count == 2
    sent_chat_ids = {call.kwargs["chat_id"] for call in application.bot.send_message.await_args_list}
    assert sent_chat_ids == {42, 99}


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_poll_events_pr_created_dedupes_origin_chat_from_notify_chats():
    """pr_created sends once per destination and only replies to the origin chat."""
    import asyncio

    from propagate_telegram.bot import _poll_events

    fake_event = {
        "event": "pr_created",
        "execution": "deploy",
        "pr_url": "https://github.com/org/repo/pull/7",
        "metadata": {"chat_id": "42", "message_id": "5"},
    }
    call_count = 0

    def fake_receive(sub_socket, timeout_ms=1000):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fake_event
        raise asyncio.CancelledError

    application = MagicMock()
    application.bot.send_message = AsyncMock()
    application.bot_data = {
        "notify_chats": {42, 99},
        "response_queue": asyncio.Queue(),
    }

    with patch("propagate_telegram.bot.receive_event", side_effect=fake_receive):
        try:
            await _poll_events(application, MagicMock())
        except asyncio.CancelledError:
            pass

    assert application.bot.send_message.await_count == 2
    sent_calls = {call.kwargs["chat_id"]: call.kwargs for call in application.bot.send_message.await_args_list}
    assert set(sent_calls) == {42, 99}
    assert sent_calls[42]["reply_to_message_id"] == 5
    assert "reply_to_message_id" not in sent_calls[99]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_poll_events_sends_pr_updated_to_notify_chats():
    """pr_updated without chat metadata is sent to configured notify chats."""
    import asyncio

    from propagate_telegram.bot import _poll_events

    fake_event = {
        "event": "pr_updated",
        "execution": "deploy",
        "pr_url": "https://github.com/org/repo/pull/7",
        "metadata": {},
    }
    call_count = 0

    def fake_receive(sub_socket, timeout_ms=1000):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fake_event
        raise asyncio.CancelledError

    application = MagicMock()
    application.bot.send_message = AsyncMock()
    application.bot_data = {
        "notify_chats": {42, 99},
        "response_queue": asyncio.Queue(),
    }

    with patch("propagate_telegram.bot.receive_event", side_effect=fake_receive):
        try:
            await _poll_events(application, MagicMock())
        except asyncio.CancelledError:
            pass

    assert application.bot.send_message.await_count == 2
    sent_chat_ids = {call.kwargs["chat_id"] for call in application.bot.send_message.await_args_list}
    assert sent_chat_ids == {42, 99}


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_poll_events_sends_run_failed_to_notify_chats():
    """run_failed without chat metadata is sent to configured notify chats."""
    import asyncio

    from propagate_telegram.bot import _poll_events

    fake_event = {
        "event": "run_failed",
        "signal_type": "deploy",
        "messages": ["something broke"],
        "metadata": {},
    }
    call_count = 0

    def fake_receive(sub_socket, timeout_ms=1000):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fake_event
        raise asyncio.CancelledError

    application = MagicMock()
    application.bot.send_message = AsyncMock()
    application.bot_data = {
        "notify_chats": {42, 99},
        "response_queue": asyncio.Queue(),
    }

    with patch("propagate_telegram.bot.receive_event", side_effect=fake_receive):
        try:
            await _poll_events(application, MagicMock())
        except asyncio.CancelledError:
            pass

    assert application.bot.send_message.await_count == 2
    sent_chat_ids = {call.kwargs["chat_id"] for call in application.bot.send_message.await_args_list}
    assert sent_chat_ids == {42, 99}
