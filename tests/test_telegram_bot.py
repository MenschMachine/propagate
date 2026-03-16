from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from propagate_app.models import SignalConfig, SignalFieldConfig
from propagate_app.signal_transport import bind_pull_socket, close_pull_socket, close_push_socket, connect_push_socket, receive_signal
from propagate_telegram.cli import _parse_allowed_users, _resolve_allowed_users, _resolve_token
from propagate_telegram.message_parser import parse_payload_params, parse_signal_message

# ---------------------------------------------------------------------------
# Parser tests (pure, no mocks)
# ---------------------------------------------------------------------------


def test_parse_signal_message_with_text():
    result = parse_signal_message("/signal deploy\nDeploy to prod.")
    assert result is not None
    signal_type, remaining = result
    assert signal_type == "deploy"
    assert remaining == "Deploy to prod."


def test_parse_signal_message_without_text():
    result = parse_signal_message("/signal deploy")
    assert result is not None
    signal_type, remaining = result
    assert signal_type == "deploy"
    assert remaining == ""


def test_parse_signal_message_empty():
    result = parse_signal_message("/signal")
    assert result is None


def test_parse_signal_message_empty_with_spaces():
    result = parse_signal_message("/signal   ")
    assert result is None


def test_parse_signal_message_multiline():
    text = "/signal deploy\nStep 1: pull latest.\nStep 2: run migrations.\nStep 3: restart."
    result = parse_signal_message(text)
    assert result is not None
    signal_type, remaining = result
    assert signal_type == "deploy"
    assert "Step 1" in remaining
    assert "Step 3" in remaining
    assert remaining.count("\n") == 2


def test_parse_signal_message_text_on_first_line():
    result = parse_signal_message("/signal deploy do the thing")
    assert result is not None
    signal_type, remaining = result
    assert signal_type == "deploy"
    assert remaining == "do the thing"


def test_parse_signal_message_text_first_line_and_rest():
    result = parse_signal_message("/signal deploy do the thing\nand more")
    assert result is not None
    signal_type, remaining = result
    assert signal_type == "deploy"
    assert remaining == "do the thing\nand more"


def test_parse_signal_message_with_bot_suffix():
    result = parse_signal_message("/signal@MyPropagateBot deploy\nDeploy to prod.")
    assert result is not None
    signal_type, remaining = result
    assert signal_type == "deploy"
    assert remaining == "Deploy to prod."


def test_parse_signal_message_with_bot_suffix_no_text():
    result = parse_signal_message("/signal@MyBot deploy")
    assert result is not None
    signal_type, remaining = result
    assert signal_type == "deploy"
    assert remaining == ""


def test_parse_signal_message_with_bot_suffix_empty():
    result = parse_signal_message("/signal@MyBot")
    assert result is None


# ---------------------------------------------------------------------------
# Payload param parsing tests
# ---------------------------------------------------------------------------


def test_parse_payload_params_kv_pairs():
    result = parse_payload_params("env:prod branch:main")
    assert result == {"env": "prod", "branch": "main"}


def test_parse_payload_params_quoted_value():
    result = parse_payload_params('env:"prod and staging" branch:main')
    assert result == {"env": "prod and staging", "branch": "main"}


def test_parse_payload_params_colon_in_value():
    result = parse_payload_params("url:http://example.com")
    assert result == {"url": "http://example.com"}


def test_parse_payload_params_invalid_token():
    with pytest.raises(ValueError, match="Invalid parameter"):
        parse_payload_params("bareword")


def test_parse_payload_params_unclosed_quote():
    with pytest.raises(ValueError, match="Unmatched quotes"):
        parse_payload_params('env:"unclosed')


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


def test_resolve_allowed_users_cli_wins(monkeypatch):
    monkeypatch.setenv("TELEGRAM_USERS", "999")
    assert _resolve_allowed_users("123,456") == "123,456"


def test_resolve_allowed_users_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_USERS", "111,222")
    assert _resolve_allowed_users(None) == "111,222"


def test_resolve_allowed_users_none(monkeypatch):
    monkeypatch.delenv("TELEGRAM_USERS", raising=False)
    assert _resolve_allowed_users(None) is None


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


def _make_edited_update(user_id: int, username: str) -> MagicMock:
    """Simulate an edited-message update where update.message is None."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.message = None
    return update


def _field(field_type: str = "string", required: bool = False) -> SignalFieldConfig:
    return SignalFieldConfig(field_type=field_type, required=required)


SIGNALS = {
    "deploy": SignalConfig(
        name="deploy",
        payload={
            "instructions": _field(),
            "sender": _field(),
        },
    ),
    "build": SignalConfig(
        name="build",
        payload={
            "instructions": _field(),
            "sender": _field(),
        },
    ),
}

MULTI_FIELD_SIGNALS = {
    "deploy": SignalConfig(
        name="deploy",
        payload={
            "env": _field(),
            "branch": _field(),
            "sender": _field(),
        },
    ),
}

REQUIRED_FIELD_SIGNALS = {
    "deploy": SignalConfig(
        name="deploy",
        payload={
            "instructions": _field(required=True),
            "sender": _field(),
        },
    ),
}


@pytest.mark.anyio
async def test_handle_signal_delivers_signal(zmq_socket, push_socket):
    from propagate_telegram.bot import handle_signal

    pull, _ = zmq_socket
    update = _make_update(123, "michael", "/signal deploy\nDeploy to prod.")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signal(update, context)

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
async def test_handle_signal_ignores_unauthorized_user(zmq_socket, push_socket, caplog):
    from propagate_telegram.bot import handle_signal

    pull, _ = zmq_socket
    update = _make_update(999, "hacker", "/signal deploy\nDo bad things.")
    context = _make_context(SIGNALS, push_socket, {123})

    with caplog.at_level(logging.WARNING, logger="propagate.telegram"):
        await handle_signal(update, context)

    update.message.reply_text.assert_not_called()
    result = receive_signal(pull, block=True, timeout_ms=500)
    assert result is None
    assert any("Unauthorized" in r.message and "hacker" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_handle_signal_rejects_unknown_signal(zmq_socket, push_socket):
    from propagate_telegram.bot import handle_signal

    pull, _ = zmq_socket
    update = _make_update(123, "michael", "/signal unknown\nSome instructions.")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signal(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "unknown" in reply_text.lower() or "not defined" in reply_text.lower()

    result = receive_signal(pull, block=True, timeout_ms=500)
    assert result is None


@pytest.mark.anyio
async def test_handle_signal_includes_sender(zmq_socket, push_socket):
    from propagate_telegram.bot import handle_signal

    pull, _ = zmq_socket
    update = _make_update(123, "michael", "/signal deploy\nDo it.")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signal(update, context)

    result = receive_signal(pull, block=True, timeout_ms=2000)
    assert result is not None
    _, payload = result
    assert payload["sender"] == "michael"


@pytest.mark.anyio
async def test_handle_signal_bad_format(push_socket):
    from propagate_telegram.bot import handle_signal

    update = _make_update(123, "michael", "/signal")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signal(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "usage" in reply_text.lower()


@pytest.mark.anyio
async def test_handle_signal_uses_user_id_when_no_username(zmq_socket, push_socket):
    from propagate_telegram.bot import handle_signal

    pull, _ = zmq_socket
    update = _make_update(123, None, "/signal deploy\nDo it.")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signal(update, context)

    result = receive_signal(pull, block=True, timeout_ms=2000)
    assert result is not None
    _, payload = result
    assert payload["sender"] == "123"


@pytest.mark.anyio
async def test_handle_signal_single_param_shorthand(zmq_socket, push_socket):
    """Signal with 1 user field + bare text → payload uses that field."""
    from propagate_telegram.bot import handle_signal

    pull, _ = zmq_socket
    update = _make_update(123, "michael", "/signal deploy Deploy to production please")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signal(update, context)

    result = receive_signal(pull, block=True, timeout_ms=2000)
    assert result is not None
    signal_type, payload = result
    assert signal_type == "deploy"
    assert payload["instructions"] == "Deploy to production please"
    assert payload["sender"] == "michael"


@pytest.mark.anyio
async def test_handle_signal_multi_param(zmq_socket, push_socket):
    """Signal with multiple fields, key:value pairs delivered via ZMQ."""
    from propagate_telegram.bot import handle_signal

    pull, _ = zmq_socket
    update = _make_update(123, "michael", "/signal deploy env:prod branch:main")
    context = _make_context(MULTI_FIELD_SIGNALS, push_socket, {123})

    await handle_signal(update, context)

    result = receive_signal(pull, block=True, timeout_ms=2000)
    assert result is not None
    signal_type, payload = result
    assert signal_type == "deploy"
    assert payload["env"] == "prod"
    assert payload["branch"] == "main"
    assert payload["sender"] == "michael"


@pytest.mark.anyio
async def test_handle_signal_unknown_field_rejected(push_socket):
    """Key not in signal config → error reply."""
    from propagate_telegram.bot import handle_signal

    update = _make_update(123, "michael", "/signal deploy bogus:value")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signal(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "unknown" in reply_text.lower() or "bogus" in reply_text.lower()


@pytest.mark.anyio
async def test_handle_signal_missing_required_field(push_socket):
    """Signal with required field but no payload → error reply."""
    from propagate_telegram.bot import handle_signal

    update = _make_update(123, "michael", "/signal deploy")
    context = _make_context(REQUIRED_FIELD_SIGNALS, push_socket, {123})

    await handle_signal(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "missing" in reply_text.lower() or "required" in reply_text.lower()


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
async def test_handle_signals_shows_parameters(push_socket):
    from propagate_telegram.bot import handle_signals

    update = _make_update(123, "michael", "/signals")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signals(update, context)

    reply_text = update.message.reply_text.call_args[0][0]
    assert "instructions (string)" in reply_text
    assert "sender" not in reply_text


@pytest.mark.anyio
async def test_handle_signals_shows_required_marker(push_socket):
    from propagate_telegram.bot import handle_signals

    update = _make_update(123, "michael", "/signals")
    context = _make_context(REQUIRED_FIELD_SIGNALS, push_socket, {123})

    await handle_signals(update, context)

    reply_text = update.message.reply_text.call_args[0][0]
    assert "instructions (string, required)" in reply_text


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
    assert "/signal" in reply_text
    assert "/signals" in reply_text


@pytest.mark.anyio
async def test_handle_signal_ignores_edited_message(push_socket):
    """Edited messages have update.message=None; handlers must not crash."""
    from propagate_telegram.bot import handle_signal

    update = _make_edited_update(123, "michael")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signal(update, context)  # should return silently


@pytest.mark.anyio
async def test_handle_signals_ignores_edited_message(push_socket):
    from propagate_telegram.bot import handle_signals

    update = _make_edited_update(123, "michael")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_signals(update, context)


@pytest.mark.anyio
async def test_handle_help_ignores_edited_message(push_socket):
    from propagate_telegram.bot import handle_help

    update = _make_edited_update(123, "michael")
    context = _make_context(SIGNALS, push_socket, {123})

    await handle_help(update, context)
