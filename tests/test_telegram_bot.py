from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from propagate_app.signal_transport import bind_pull_socket, close_pull_socket, close_push_socket, connect_push_socket, receive_signal
from propagate_telegram.cli import _parse_allowed_users, _resolve_token
from propagate_telegram.message_parser import parse_run_message

# ---------------------------------------------------------------------------
# Parser tests (pure, no mocks)
# ---------------------------------------------------------------------------


def test_parse_run_message_with_instructions():
    result = parse_run_message("/run deploy\nDeploy to prod.")
    assert result is not None
    signal_type, payload = result
    assert signal_type == "deploy"
    assert payload["instructions"] == "Deploy to prod."


def test_parse_run_message_without_instructions():
    result = parse_run_message("/run deploy")
    assert result is not None
    signal_type, payload = result
    assert signal_type == "deploy"
    assert payload == {}


def test_parse_run_message_empty():
    result = parse_run_message("/run")
    assert result is None


def test_parse_run_message_empty_with_spaces():
    result = parse_run_message("/run   ")
    assert result is None


def test_parse_run_message_multiline():
    text = "/run deploy\nStep 1: pull latest.\nStep 2: run migrations.\nStep 3: restart."
    result = parse_run_message(text)
    assert result is not None
    signal_type, payload = result
    assert signal_type == "deploy"
    assert "Step 1" in payload["instructions"]
    assert "Step 3" in payload["instructions"]
    assert payload["instructions"].count("\n") == 2


def test_parse_run_message_instructions_on_first_line():
    result = parse_run_message("/run deploy do the thing")
    assert result is not None
    signal_type, payload = result
    assert signal_type == "deploy"
    assert payload["instructions"] == "do the thing"


def test_parse_run_message_instructions_first_line_and_rest():
    result = parse_run_message("/run deploy do the thing\nand more")
    assert result is not None
    signal_type, payload = result
    assert signal_type == "deploy"
    assert payload["instructions"] == "do the thing\nand more"


def test_parse_run_message_with_bot_suffix():
    result = parse_run_message("/run@MyPropagateBot deploy\nDeploy to prod.")
    assert result is not None
    signal_type, payload = result
    assert signal_type == "deploy"
    assert payload["instructions"] == "Deploy to prod."


def test_parse_run_message_with_bot_suffix_no_instructions():
    result = parse_run_message("/run@MyBot deploy")
    assert result is not None
    signal_type, payload = result
    assert signal_type == "deploy"
    assert payload == {}


def test_parse_run_message_with_bot_suffix_empty():
    result = parse_run_message("/run@MyBot")
    assert result is None


# ---------------------------------------------------------------------------
# CLI helper tests
# ---------------------------------------------------------------------------


def test_resolve_token_direct():
    assert _resolve_token("abc123", None) == "abc123"


def test_resolve_token_from_env(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "from-env")
    assert _resolve_token(None, "MY_TOKEN") == "from-env"


def test_resolve_token_missing_env(monkeypatch):
    monkeypatch.delenv("MY_TOKEN", raising=False)
    with pytest.raises(Exception, match="not set"):
        _resolve_token(None, "MY_TOKEN")


def test_resolve_token_both_raises():
    with pytest.raises(Exception, match="Cannot specify both"):
        _resolve_token("abc", "MY_TOKEN")


def test_resolve_token_neither_raises():
    with pytest.raises(Exception, match="Must specify"):
        _resolve_token(None, None)


def test_parse_allowed_users():
    assert _parse_allowed_users("123,456,789") == {123, 456, 789}


def test_parse_allowed_users_single():
    assert _parse_allowed_users("42") == {42}


def test_parse_allowed_users_with_spaces():
    assert _parse_allowed_users("123, 456 , 789") == {123, 456, 789}


def test_parse_allowed_users_invalid():
    with pytest.raises(Exception, match="Invalid user ID"):
        _parse_allowed_users("123,abc")


# ---------------------------------------------------------------------------
# Handler tests (mock Telegram, real ZMQ)
# ---------------------------------------------------------------------------


@pytest.fixture
def zmq_socket():
    address = "ipc:///tmp/propagate-test-telegram.sock"
    pull = bind_pull_socket(address)
    yield pull, address
    close_pull_socket(pull, address)


@pytest.fixture
def push_socket(zmq_socket):
    _, address = zmq_socket
    socket = connect_push_socket(address)
    yield socket
    close_push_socket(socket)


def _make_update(user_id: int, username: str, text: str) -> MagicMock:
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_context(config_signals: dict, push_socket, allowed_users: set[int]) -> MagicMock:
    context = MagicMock()
    context.bot_data = {
        "config_signals": config_signals,
        "push_socket": push_socket,
        "allowed_users": allowed_users,
    }
    return context


SIGNALS = {"deploy": object(), "build": object()}


@pytest.mark.anyio
async def test_handle_run_delivers_signal(zmq_socket, push_socket):
    from propagate_telegram.bot import handle_run

    pull, _ = zmq_socket
    update = _make_update(123, "michael", "/run deploy\nDeploy to prod.")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_run(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "deploy" in reply_text.lower()

    result = receive_signal(pull, block=True, timeout_ms=2000)
    assert result is not None
    signal_type, payload = result
    assert signal_type == "deploy"
    assert payload["instructions"] == "Deploy to prod."
    assert payload["sender"] == "michael"


@pytest.mark.anyio
async def test_handle_run_ignores_unauthorized_user(zmq_socket, push_socket):
    from propagate_telegram.bot import handle_run

    pull, _ = zmq_socket
    update = _make_update(999, "hacker", "/run deploy\nDo bad things.")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_run(update, context)

    update.message.reply_text.assert_not_called()
    result = receive_signal(pull, block=True, timeout_ms=500)
    assert result is None


@pytest.mark.anyio
async def test_handle_run_rejects_unknown_signal(zmq_socket, push_socket):
    from propagate_telegram.bot import handle_run

    pull, _ = zmq_socket
    update = _make_update(123, "michael", "/run unknown\nSome instructions.")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_run(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "unknown" in reply_text.lower() or "not defined" in reply_text.lower()

    result = receive_signal(pull, block=True, timeout_ms=500)
    assert result is None


@pytest.mark.anyio
async def test_handle_run_includes_sender(zmq_socket, push_socket):
    from propagate_telegram.bot import handle_run

    pull, _ = zmq_socket
    update = _make_update(123, "michael", "/run deploy\nDo it.")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_run(update, context)

    result = receive_signal(pull, block=True, timeout_ms=2000)
    assert result is not None
    _, payload = result
    assert payload["sender"] == "michael"


@pytest.mark.anyio
async def test_handle_run_bad_format(push_socket):
    from propagate_telegram.bot import handle_run

    update = _make_update(123, "michael", "/run")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_run(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "usage" in reply_text.lower()


@pytest.mark.anyio
async def test_handle_run_uses_user_id_when_no_username(zmq_socket, push_socket):
    from propagate_telegram.bot import handle_run

    pull, _ = zmq_socket
    update = _make_update(123, None, "/run deploy\nDo it.")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_run(update, context)

    result = receive_signal(pull, block=True, timeout_ms=2000)
    assert result is not None
    _, payload = result
    assert payload["sender"] == "123"


@pytest.mark.anyio
async def test_handle_signals_lists_configured_signals(push_socket):
    from propagate_telegram.bot import handle_signals

    update = _make_update(123, "michael", "/signals")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signals(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "build" in reply_text
    assert "deploy" in reply_text


@pytest.mark.anyio
async def test_handle_signals_ignores_unauthorized_user(push_socket):
    from propagate_telegram.bot import handle_signals

    update = _make_update(999, "hacker", "/signals")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signals(update, context)

    update.message.reply_text.assert_not_called()


@pytest.mark.anyio
async def test_handle_help_includes_signals(push_socket):
    from propagate_telegram.bot import handle_help

    update = _make_update(123, "michael", "/help")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_help(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "build" in reply_text
    assert "deploy" in reply_text
    assert "/run" in reply_text
    assert "/signals" in reply_text
