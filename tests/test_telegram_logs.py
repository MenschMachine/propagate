from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from propagate_app.log_buffer import BufferedLogHandler, get_recent_logs


# ---------------------------------------------------------------------------
# BufferedLogHandler unit tests
# ---------------------------------------------------------------------------


def test_buffered_handler_captures_logs():
    handler = BufferedLogHandler(maxlen=10)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("test.buffered.capture")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.info("hello")
        logger.info("world")
        assert list(handler.buffer) == ["hello", "world"]
    finally:
        logger.removeHandler(handler)


def test_buffered_handler_respects_maxlen():
    handler = BufferedLogHandler(maxlen=3)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("test.buffered.maxlen")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        for i in range(5):
            logger.info("line %d", i)
        assert list(handler.buffer) == ["line 2", "line 3", "line 4"]
    finally:
        logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# get_recent_logs tests
# ---------------------------------------------------------------------------


def test_get_recent_logs_returns_correct_count(monkeypatch):
    handler = BufferedLogHandler(maxlen=100)
    handler.setFormatter(logging.Formatter("%(message)s"))
    monkeypatch.setattr("propagate_app.log_buffer._buffered_handler", handler)

    logger = logging.getLogger("test.recent")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        for i in range(10):
            logger.info("msg %d", i)
        result = get_recent_logs(3)
        assert len(result) == 3
        assert result == ["msg 7", "msg 8", "msg 9"]
    finally:
        logger.removeHandler(handler)


def test_get_recent_logs_returns_all_when_fewer_than_n(monkeypatch):
    handler = BufferedLogHandler(maxlen=100)
    handler.setFormatter(logging.Formatter("%(message)s"))
    monkeypatch.setattr("propagate_app.log_buffer._buffered_handler", handler)

    logger = logging.getLogger("test.recent.few")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.info("only one")
        result = get_recent_logs(50)
        assert result == ["only one"]
    finally:
        logger.removeHandler(handler)


def test_get_recent_logs_no_handler(monkeypatch):
    monkeypatch.setattr("propagate_app.log_buffer._buffered_handler", None)
    assert get_recent_logs(10) == []


# ---------------------------------------------------------------------------
# handle_logs handler tests
# ---------------------------------------------------------------------------


def _make_update(user_id: int, username: str, text: str) -> MagicMock:
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_context(allowed_users: set[int]) -> MagicMock:
    context = MagicMock()
    context.bot_data = {"allowed_users": allowed_users}
    return context


@pytest.mark.anyio
async def test_handle_logs_default_n(monkeypatch):
    from propagate_telegram.bot import handle_logs

    handler = BufferedLogHandler(maxlen=100)
    handler.setFormatter(logging.Formatter("%(message)s"))
    monkeypatch.setattr("propagate_app.log_buffer._buffered_handler", handler)

    logger = logging.getLogger("test.handle.default")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        for i in range(25):
            logger.info("line %d", i)

        update = _make_update(123, "michael", "/logs")
        context = _make_context({123})
        await handle_logs(update, context)

        reply = update.message.reply_text.call_args[0][0]
        # Default is 20 lines
        assert reply.count("\n") == 19  # 20 lines = 19 newlines
        assert "line 24" in reply
        assert "line 5" in reply
        assert "line 4" not in reply
    finally:
        logger.removeHandler(handler)


@pytest.mark.anyio
async def test_handle_logs_explicit_n(monkeypatch):
    from propagate_telegram.bot import handle_logs

    handler = BufferedLogHandler(maxlen=100)
    handler.setFormatter(logging.Formatter("%(message)s"))
    monkeypatch.setattr("propagate_app.log_buffer._buffered_handler", handler)

    logger = logging.getLogger("test.handle.explicit")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        for i in range(10):
            logger.info("entry %d", i)

        update = _make_update(123, "michael", "/logs 3")
        context = _make_context({123})
        await handle_logs(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert reply == "entry 7\nentry 8\nentry 9"
    finally:
        logger.removeHandler(handler)


@pytest.mark.anyio
async def test_handle_logs_non_numeric_n():
    from propagate_telegram.bot import handle_logs

    update = _make_update(123, "michael", "/logs abc")
    context = _make_context({123})
    await handle_logs(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "must be a number" in reply.lower()


@pytest.mark.anyio
async def test_handle_logs_unauthorized():
    from propagate_telegram.bot import handle_logs

    update = _make_update(999, "hacker", "/logs")
    context = _make_context({123})
    await handle_logs(update, context)

    update.message.reply_text.assert_not_called()


@pytest.mark.anyio
async def test_handle_logs_no_logs_available(monkeypatch):
    from propagate_telegram.bot import handle_logs

    handler = BufferedLogHandler(maxlen=100)
    monkeypatch.setattr("propagate_app.log_buffer._buffered_handler", handler)

    update = _make_update(123, "michael", "/logs")
    context = _make_context({123})
    await handle_logs(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "no logs" in reply.lower()


@pytest.mark.anyio
async def test_handle_logs_truncates_to_telegram_limit(monkeypatch):
    from propagate_telegram.bot import handle_logs

    handler = BufferedLogHandler(maxlen=500)
    handler.setFormatter(logging.Formatter("%(message)s"))
    monkeypatch.setattr("propagate_app.log_buffer._buffered_handler", handler)

    logger = logging.getLogger("test.handle.truncate")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        # Each line ~100 chars, 500 lines = ~50k chars >> 4096
        for i in range(500):
            logger.info("x" * 95 + " %04d", i)

        update = _make_update(123, "michael", "/logs 500")
        context = _make_context({123})
        await handle_logs(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert len(reply) <= 4096
        # Every line should be complete (no mid-line cut)
        for line in reply.split("\n"):
            assert line.endswith(("0", "1", "2", "3", "4", "5", "6", "7", "8", "9"))
    finally:
        logger.removeHandler(handler)


@pytest.mark.anyio
async def test_handle_logs_ignores_edited_message():
    from propagate_telegram.bot import handle_logs

    update = MagicMock()
    update.effective_user.id = 123
    update.effective_user.username = "michael"
    update.message = None
    context = _make_context({123})

    await handle_logs(update, context)  # should not crash
