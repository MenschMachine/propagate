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


def _make_project(name, signals, address, pub_address="ipc:///tmp/fake-pub.sock"):
    return ProjectState(
        name=name,
        config_signals=signals,
        zmq_address=address,
        pub_address=pub_address,
    )


def _make_update(user_id: int, username: str, text: str, chat_id: int = 100) -> MagicMock:
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.message_id = 1
    update.message.reply_text = AsyncMock()
    return update


def _make_context_multi(projects: dict[str, ProjectState], active_project: dict | None = None) -> MagicMock:
    context = MagicMock()
    context.bot_data = {
        "projects": projects,
        "active_project": active_project if active_project is not None else {},
        "allowed_users": {123},
    }
    return context


def _make_context_single(project: ProjectState) -> MagicMock:
    return _make_context_multi({project.name: project})


# ---------------------------------------------------------------------------
# /project command
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_project_list():
    """``/project`` lists all projects, marks the active one."""
    from propagate_telegram.bot import handle_project

    proj_a = _make_project("alpha", SIGNALS_A, "ipc:///tmp/a.sock")
    proj_b = _make_project("beta", SIGNALS_B, "ipc:///tmp/b.sock")
    projects = {"alpha": proj_a, "beta": proj_b}

    update = _make_update(123, "michael", "/project", chat_id=100)
    ctx = _make_context_multi(projects, active_project={100: "alpha"})

    await handle_project(update, ctx)

    reply = update.message.reply_text.call_args[0][0]
    assert "alpha" in reply
    assert "beta" in reply
    assert "(active)" in reply


@pytest.mark.anyio
async def test_project_switch():
    """``/project foo`` sets the active project and confirms."""
    from propagate_telegram.bot import handle_project

    proj_a = _make_project("alpha", SIGNALS_A, "ipc:///tmp/a.sock")
    proj_b = _make_project("beta", SIGNALS_B, "ipc:///tmp/b.sock")
    projects = {"alpha": proj_a, "beta": proj_b}

    update = _make_update(123, "michael", "/project beta", chat_id=100)
    active = {}
    ctx = _make_context_multi(projects, active_project=active)

    await handle_project(update, ctx)

    assert active[100] == "beta"
    reply = update.message.reply_text.call_args[0][0]
    assert "beta" in reply


@pytest.mark.anyio
async def test_project_unknown():
    """``/project bad`` replies with an error."""
    from propagate_telegram.bot import handle_project

    proj_a = _make_project("alpha", SIGNALS_A, "ipc:///tmp/a.sock")
    projects = {"alpha": proj_a}

    update = _make_update(123, "michael", "/project bad", chat_id=100)
    ctx = _make_context_multi(projects)

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

    proj_a = _make_project("alpha", SIGNALS_A, "ipc:///tmp/a.sock")
    proj_b = _make_project("beta", SIGNALS_B, "ipc:///tmp/b.sock")
    projects = {"alpha": proj_a, "beta": proj_b}

    update = _make_update(123, "michael", "/signal deploy\nDo it.", chat_id=100)
    ctx = _make_context_multi(projects)

    await handle_signal(update, ctx)

    reply = update.message.reply_text.call_args[0][0]
    assert "/project" in reply


@pytest.mark.anyio
async def test_signal_single_project_auto():
    """With 1 project, /signal works without /project."""
    from propagate_telegram.bot import handle_signal

    address = "ipc:///tmp/propagate-test-telegram-single.sock"
    pull = bind_pull_socket(address)
    try:
        proj = _make_project("solo", SIGNALS_A, address)
        proj.push_socket = connect_push_socket(address)
        try:
            update = _make_update(123, "michael", "/signal deploy\nDo it.", chat_id=100)
            ctx = _make_context_single(proj)

            await handle_signal(update, ctx)

            reply = update.message.reply_text.call_args[0][0]
            assert "delivered" in reply.lower()

            result = receive_signal(pull, block=True, timeout_ms=2000)
            assert result is not None
            signal_type, payload = result
            assert signal_type == "deploy"
        finally:
            close_push_socket(proj.push_socket)
    finally:
        close_pull_socket(pull, address)


@pytest.mark.anyio
async def test_signal_routes_to_active():
    """With 2 projects, signal goes to the active project's socket."""
    from propagate_telegram.bot import handle_signal

    addr_a = "ipc:///tmp/propagate-test-telegram-route-a.sock"
    addr_b = "ipc:///tmp/propagate-test-telegram-route-b.sock"
    pull_a = bind_pull_socket(addr_a)
    pull_b = bind_pull_socket(addr_b)
    try:
        proj_a = _make_project("alpha", SIGNALS_A, addr_a)
        proj_b = _make_project("beta", SIGNALS_B, addr_b)
        proj_a.push_socket = connect_push_socket(addr_a)
        proj_b.push_socket = connect_push_socket(addr_b)
        try:
            projects = {"alpha": proj_a, "beta": proj_b}
            update = _make_update(123, "michael", "/signal deploy\nDo it.", chat_id=100)
            ctx = _make_context_multi(projects, active_project={100: "alpha"})

            await handle_signal(update, ctx)

            reply = update.message.reply_text.call_args[0][0]
            assert "delivered" in reply.lower()

            result_a = receive_signal(pull_a, block=True, timeout_ms=2000)
            assert result_a is not None
            assert result_a[0] == "deploy"

            # Nothing on project B
            result_b = receive_signal(pull_b, block=True, timeout_ms=500)
            assert result_b is None
        finally:
            close_push_socket(proj_a.push_socket)
            close_push_socket(proj_b.push_socket)
    finally:
        close_pull_socket(pull_a, addr_a)
        close_pull_socket(pull_b, addr_b)


@pytest.mark.anyio
async def test_resume_routes_to_active():
    """With 2 projects, /resume goes to the active project's socket."""
    from propagate_telegram.bot import handle_resume

    addr_a = "ipc:///tmp/propagate-test-telegram-resume-a.sock"
    pull_a = bind_pull_socket(addr_a)
    try:
        proj_a = _make_project("alpha", SIGNALS_A, addr_a)
        proj_b = _make_project("beta", SIGNALS_B, "ipc:///tmp/fake-b.sock")
        proj_a.push_socket = connect_push_socket(addr_a)
        try:
            projects = {"alpha": proj_a, "beta": proj_b}
            update = _make_update(123, "michael", "/resume", chat_id=100)
            ctx = _make_context_multi(projects, active_project={100: "alpha"})

            await handle_resume(update, ctx)

            reply = update.message.reply_text.call_args[0][0]
            assert "delivered" in reply.lower()
        finally:
            close_push_socket(proj_a.push_socket)
    finally:
        close_pull_socket(pull_a, addr_a)


@pytest.mark.anyio
async def test_signals_shows_active_project():
    """``/signals`` shows the active project's signals."""
    from propagate_telegram.bot import handle_signals

    proj_a = _make_project("alpha", SIGNALS_A, "ipc:///tmp/a.sock")
    proj_b = _make_project("beta", SIGNALS_B, "ipc:///tmp/b.sock")
    projects = {"alpha": proj_a, "beta": proj_b}

    update = _make_update(123, "michael", "/signals", chat_id=100)
    ctx = _make_context_multi(projects, active_project={100: "alpha"})

    await handle_signals(update, ctx)

    reply = update.message.reply_text.call_args[0][0]
    assert "deploy" in reply
    assert "build" not in reply
    assert "[alpha]" in reply


@pytest.mark.anyio
async def test_event_reply_prefixed_multi():
    """Event reply has [name] prefix with 2 projects."""
    import asyncio
    from unittest.mock import patch

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

    with patch("propagate_telegram.bot.receive_event", side_effect=fake_receive):
        try:
            await _poll_events(app, MagicMock(), project_name="alpha")
        except asyncio.CancelledError:
            pass

    app.bot.send_message.assert_called_once()
    text = app.bot.send_message.call_args[1]["text"]
    assert text.startswith("[alpha]")


@pytest.mark.anyio
async def test_event_reply_no_prefix_single():
    """Event reply has no prefix with 1 project (project_name=None)."""
    import asyncio
    from unittest.mock import patch

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

    with patch("propagate_telegram.bot.receive_event", side_effect=fake_receive):
        try:
            await _poll_events(app, MagicMock(), project_name=None)
        except asyncio.CancelledError:
            pass

    app.bot.send_message.assert_called_once()
    text = app.bot.send_message.call_args[1]["text"]
    assert not text.startswith("[")


def test_telegram_cli_duplicate_config_stems_rejected(tmp_path):
    """Two configs with the same filename stem are rejected."""
    from propagate_telegram.cli import main

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    config_a = dir_a / "propagate.yaml"
    config_b = dir_b / "propagate.yaml"
    config_a.touch()
    config_b.touch()

    fake_config_a = MagicMock()
    fake_config_a.config_path = config_a
    fake_config_a.signals = {}
    fake_config_b = MagicMock()
    fake_config_b.config_path = config_b
    fake_config_b.signals = {}

    with (
        patch("propagate_telegram.cli.build_parser") as mock_parser,
        patch("propagate_app.config_load.load_config", side_effect=[fake_config_a, fake_config_b]),
    ):
        ns = MagicMock()
        ns.config = [str(config_a), str(config_b)]
        ns.token = "fake-token"
        ns.token_env = None
        ns.allowed_users = "123"
        ns.debug = False
        mock_parser.return_value.parse_args.return_value = ns

        result = main()

    assert result == 1
