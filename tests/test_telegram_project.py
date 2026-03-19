"""Tests for multi-project Telegram bot support."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from propagate_app.models import SignalConfig, SignalFieldConfig
from propagate_app.signal_transport import bind_pull_socket, close_pull_socket, close_push_socket, connect_push_socket, receive_signal
from propagate_telegram.bot import ProjectState


def _field(field_type: str = "string", required: bool = False) -> SignalFieldConfig:
    return SignalFieldConfig(field_type=field_type, required=required)


SIGNALS_A = {
    "deploy": SignalConfig(
        name="deploy",
        payload={"instructions": _field(), "sender": _field()},
    ),
}

SIGNALS_B = {
    "build": SignalConfig(
        name="build",
        payload={"instructions": _field(), "sender": _field()},
    ),
}


def _make_project(name, signals):
    return ProjectState(name=name, config_signals=signals)


def _make_update(user_id: int, username: str, text: str, chat_id: int = 100) -> MagicMock:
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.message_id = 1
    update.message.reply_text = AsyncMock()
    return update


def _make_context(projects: dict[str, ProjectState], active_project: dict | None = None, push_socket: MagicMock | None = None) -> MagicMock:
    context = MagicMock()
    context.bot_data = {
        "projects": projects,
        "active_project": active_project if active_project is not None else {},
        "allowed_users": {123},
        "push_socket": push_socket or MagicMock(),
    }
    return context


# ---------------------------------------------------------------------------
# /project command
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_project_list():
    """``/project`` lists all projects, marks the active one."""
    from propagate_telegram.bot import handle_project

    proj_a = _make_project("alpha", SIGNALS_A)
    proj_b = _make_project("beta", SIGNALS_B)
    projects = {"alpha": proj_a, "beta": proj_b}

    update = _make_update(123, "michael", "/project", chat_id=100)
    ctx = _make_context(projects, active_project={100: "alpha"})

    await handle_project(update, ctx)

    reply = update.message.reply_text.call_args[0][0]
    assert "alpha" in reply
    assert "beta" in reply
    assert "(active)" in reply


@pytest.mark.anyio
async def test_project_switch():
    """``/project foo`` sets the active project and confirms."""
    from propagate_telegram.bot import handle_project

    proj_a = _make_project("alpha", SIGNALS_A)
    proj_b = _make_project("beta", SIGNALS_B)
    projects = {"alpha": proj_a, "beta": proj_b}

    update = _make_update(123, "michael", "/project beta", chat_id=100)
    active = {}
    ctx = _make_context(projects, active_project=active)

    await handle_project(update, ctx)

    assert active[100] == "beta"
    reply = update.message.reply_text.call_args[0][0]
    assert "beta" in reply


@pytest.mark.anyio
async def test_project_unknown():
    """``/project bad`` replies with an error."""
    from propagate_telegram.bot import handle_project

    proj_a = _make_project("alpha", SIGNALS_A)
    projects = {"alpha": proj_a}

    update = _make_update(123, "michael", "/project bad", chat_id=100)
    ctx = _make_context(projects)

    await handle_project(update, ctx)

    reply = update.message.reply_text.call_args[0][0]
    assert "Unknown project" in reply or "bad" in reply


# ---------------------------------------------------------------------------
# Signal routing
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_signal_no_project_prompts():
    """With 2 projects and no selection, /signal prompts the user."""
    from propagate_telegram.bot import handle_signal

    proj_a = _make_project("alpha", SIGNALS_A)
    proj_b = _make_project("beta", SIGNALS_B)
    projects = {"alpha": proj_a, "beta": proj_b}

    update = _make_update(123, "michael", "/signal deploy\nDo it.", chat_id=100)
    ctx = _make_context(projects)

    await handle_signal(update, ctx)

    reply = update.message.reply_text.call_args[0][0]
    assert "/project" in reply


@pytest.mark.anyio
async def test_signal_single_project_auto():
    """With 1 project, /signal works without /project."""
    from propagate_telegram.bot import handle_signal

    address = "ipc:///tmp/propagate-test-telegram-single.sock"
    pull = bind_pull_socket(address)
    push = connect_push_socket(address)
    try:
        proj = _make_project("solo", SIGNALS_A)
        update = _make_update(123, "michael", "/signal deploy\nDo it.", chat_id=100)
        ctx = _make_context({"solo": proj}, push_socket=push)

        await handle_signal(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        assert "delivered" in reply.lower()

        result = receive_signal(pull, block=True, timeout_ms=2000)
        assert result is not None
        signal_type, payload = result
        assert signal_type == "deploy"
    finally:
        close_push_socket(push)
        close_pull_socket(pull, address)


@pytest.mark.anyio
async def test_signal_routes_to_active():
    """With 2 projects, signal includes the active project in metadata."""
    from propagate_telegram.bot import handle_signal

    address = "ipc:///tmp/propagate-test-telegram-route.sock"
    pull = bind_pull_socket(address)
    push = connect_push_socket(address)
    try:
        proj_a = _make_project("alpha", SIGNALS_A)
        proj_b = _make_project("beta", SIGNALS_B)
        projects = {"alpha": proj_a, "beta": proj_b}

        update = _make_update(123, "michael", "/signal deploy\nDo it.", chat_id=100)
        ctx = _make_context(projects, active_project={100: "alpha"}, push_socket=push)

        await handle_signal(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        assert "delivered" in reply.lower()

        from propagate_app.signal_transport import receive_message
        result = receive_message(pull, block=True, timeout_ms=2000)
        assert result is not None
        kind, name, payload, metadata = result
        assert kind == "signal"
        assert name == "deploy"
        assert metadata.get("project") == "alpha"
    finally:
        close_push_socket(push)
        close_pull_socket(pull, address)


@pytest.mark.anyio
async def test_resume_routes_to_active():
    """With 2 projects, /resume includes the active project in metadata."""
    from propagate_telegram.bot import handle_resume

    address = "ipc:///tmp/propagate-test-telegram-resume.sock"
    pull = bind_pull_socket(address)
    push = connect_push_socket(address)
    try:
        proj_a = _make_project("alpha", SIGNALS_A)
        proj_b = _make_project("beta", SIGNALS_B)
        projects = {"alpha": proj_a, "beta": proj_b}

        update = _make_update(123, "michael", "/resume", chat_id=100)
        ctx = _make_context(projects, active_project={100: "alpha"}, push_socket=push)

        await handle_resume(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        assert "delivered" in reply.lower()

        from propagate_app.signal_transport import receive_message
        result = receive_message(pull, block=True, timeout_ms=2000)
        assert result is not None
        kind, name, payload, metadata = result
        assert kind == "command"
        assert name == "resume"
        assert metadata.get("project") == "alpha"
    finally:
        close_push_socket(push)
        close_pull_socket(pull, address)


@pytest.mark.anyio
async def test_signals_shows_active_project():
    """``/signals`` shows the active project's signals."""
    from propagate_telegram.bot import handle_signals

    proj_a = _make_project("alpha", SIGNALS_A)
    proj_b = _make_project("beta", SIGNALS_B)
    projects = {"alpha": proj_a, "beta": proj_b}

    update = _make_update(123, "michael", "/signals", chat_id=100)
    ctx = _make_context(projects, active_project={100: "alpha"})

    await handle_signals(update, ctx)

    reply = update.message.reply_text.call_args[0][0]
    assert "deploy" in reply
    assert "build" not in reply
    assert "[alpha]" in reply


@pytest.mark.anyio
async def test_event_reply_prefixed_multi():
    """Event reply has [name] prefix from coordinator project field."""
    import asyncio

    from propagate_telegram.bot import _poll_events

    fake_event = {
        "event": "run_completed",
        "signal_type": "deploy",
        "project": "alpha",
        "metadata": {"chat_id": "100", "message_id": "1"},
        "messages": ["Done."],
    }
    call_count = 0

    def fake_receive(sub_socket, timeout_ms=1000):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fake_event
        raise asyncio.CancelledError

    app = MagicMock()
    app.bot.send_message = AsyncMock()
    app.bot_data = {"response_queue": asyncio.Queue()}

    with patch("propagate_telegram.bot.receive_event", side_effect=fake_receive):
        try:
            await _poll_events(app, MagicMock())
        except asyncio.CancelledError:
            pass

    app.bot.send_message.assert_called_once()
    text = app.bot.send_message.call_args[1]["text"]
    assert text.startswith("[alpha]")


@pytest.mark.anyio
async def test_event_reply_no_prefix_when_no_project():
    """Event reply has no prefix when project field is absent."""
    import asyncio

    from propagate_telegram.bot import _poll_events

    fake_event = {
        "event": "run_completed",
        "signal_type": "deploy",
        "metadata": {"chat_id": "100", "message_id": "1"},
        "messages": ["Done."],
    }
    call_count = 0

    def fake_receive(sub_socket, timeout_ms=1000):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fake_event
        raise asyncio.CancelledError

    app = MagicMock()
    app.bot.send_message = AsyncMock()
    app.bot_data = {"response_queue": asyncio.Queue()}

    with patch("propagate_telegram.bot.receive_event", side_effect=fake_receive):
        try:
            await _poll_events(app, MagicMock())
        except asyncio.CancelledError:
            pass

    app.bot.send_message.assert_called_once()
    text = app.bot.send_message.call_args[1]["text"]
    assert not text.startswith("[")


@pytest.mark.anyio
async def test_no_projects_prompts_list():
    """With empty projects, /signal says 'No projects loaded'."""
    from propagate_telegram.bot import handle_signal

    update = _make_update(123, "michael", "/signal deploy\nDo it.", chat_id=100)
    ctx = _make_context({})

    await handle_signal(update, ctx)

    reply = update.message.reply_text.call_args[0][0]
    assert "No projects loaded" in reply
