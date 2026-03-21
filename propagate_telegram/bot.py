from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from propagate_app.event_format import format_event_reply
from propagate_app.message_parser import validate_and_build_payload
from propagate_app.signal_transport import (
    COORDINATOR_ADDRESS,
    COORDINATOR_PUB_ADDRESS,
    close_push_socket,
    close_sub_socket,
    connect_push_socket,
    connect_sub_socket,
    receive_event,
    send_command,
    send_coordinator_command,
    send_signal,
)

from .message_parser import parse_signal_message

logger = logging.getLogger("propagate.telegram")
_TELEGRAM_NOTIFY_EVENTS = {"pr_created", "pr_updated", "run_failed"}


@dataclass
class ProjectState:
    name: str
    config_signals: dict[str, Any]


def _is_allowed(update, allowed_users: set[int]) -> bool:
    user = update.effective_user
    if user is None:
        return False
    if user.id in allowed_users:
        return True
    username = user.username or str(user.id)
    logger.warning("Unauthorized command from user %s (id=%d).", username, user.id)
    return False


def _resolve_project(bot_data: dict[str, Any], chat_id: int) -> ProjectState | None:
    """Return the active project for a chat, auto-selecting if only one exists."""
    projects: dict[str, ProjectState] = bot_data["projects"]
    if len(projects) == 1:
        return next(iter(projects.values()))
    active_project: dict[int, str] = bot_data["active_project"]
    name = active_project.get(chat_id)
    if name is not None and name in projects:
        return projects[name]
    return None


async def _require_project(update, bot_data: dict[str, Any]) -> ProjectState | None:
    """Resolve the active project; reply with a prompt if ambiguous."""
    project = _resolve_project(bot_data, update.message.chat_id)
    if project is not None:
        return project
    projects: dict[str, ProjectState] = bot_data["projects"]
    if not projects:
        await update.message.reply_text("No projects loaded. Use /list to refresh.")
        return None
    names = ", ".join(sorted(projects))
    await update.message.reply_text(
        f"Multiple projects loaded. Select one with /project <name>.\nAvailable: {names}"
    )
    return None


async def handle_project(update, context) -> None:
    """Handle the ``/project`` command: list or switch active project."""
    bot_data: dict[str, Any] = context.bot_data
    allowed_users: set[int] = bot_data["allowed_users"]

    if not _is_allowed(update, allowed_users):
        return

    if update.message is None:
        return

    text: str = update.message.text
    parts = text.strip().split()
    projects: dict[str, ProjectState] = bot_data["projects"]
    active_project: dict[int, str] = bot_data["active_project"]
    chat_id = update.message.chat_id

    if len(parts) <= 1:
        current = active_project.get(chat_id)
        lines: list[str] = []
        for name in sorted(projects):
            marker = " (active)" if name == current else ""
            lines.append(f"  {name}{marker}")
        await update.message.reply_text("Projects:\n" + "\n".join(lines))
        return

    name = parts[1]
    if name not in projects:
        available = ", ".join(sorted(projects))
        await update.message.reply_text(f"Unknown project '{name}'. Available: {available}")
        return

    active_project[chat_id] = name
    await update.message.reply_text(f"Switched to project '{name}'.")


async def handle_signal(update, context) -> None:
    """Handle the ``/signal`` command: parse, validate, and deliver a signal."""
    bot_data: dict[str, Any] = context.bot_data
    allowed_users: set[int] = bot_data["allowed_users"]

    if not _is_allowed(update, allowed_users):
        return

    if update.message is None:
        return

    project = await _require_project(update, bot_data)
    if project is None:
        return

    text: str = update.message.text
    result = parse_signal_message(text)
    if result is None:
        await update.message.reply_text("Usage: /signal <signal> [param:value ...]")
        return

    signal_type, remaining = result
    config_signals = project.config_signals

    if signal_type not in config_signals:
        defined = ", ".join(sorted(config_signals))
        await update.message.reply_text(f"Signal '{signal_type}' not defined in config (defined: {defined}).")
        return

    signal_config = config_signals[signal_type]

    payload, errors = validate_and_build_payload(remaining, signal_config)
    if errors:
        await update.message.reply_text(errors[0])
        return

    sender = update.effective_user.username or str(update.effective_user.id)
    payload["sender"] = sender

    metadata = {
        "project": project.name,
        "chat_id": str(update.message.chat_id),
        "message_id": str(update.message.message_id),
    }
    push_socket = bot_data["push_socket"]
    send_signal(push_socket, signal_type, payload, metadata=metadata)
    logger.info("Delivered signal '%s' from %s.", signal_type, sender)
    await update.message.reply_text(f"Signal '{signal_type}' delivered.")


async def handle_resume(update, context) -> None:
    """Handle the ``/resume`` command: resume a failed run."""
    bot_data: dict[str, Any] = context.bot_data
    allowed_users: set[int] = bot_data["allowed_users"]

    if not _is_allowed(update, allowed_users):
        return

    if update.message is None:
        return

    project = await _require_project(update, bot_data)
    if project is None:
        return

    metadata = {
        "project": project.name,
        "chat_id": str(update.message.chat_id),
        "message_id": str(update.message.message_id),
    }
    push_socket = bot_data["push_socket"]
    send_command(push_socket, "resume", metadata=metadata)
    sender = update.effective_user.username or str(update.effective_user.id)
    logger.info("Resume command from %s.", sender)
    await update.message.reply_text("Resume command delivered.")


async def handle_signals(update, context) -> None:
    """Handle the ``/signals`` command: list configured signals."""
    allowed_users: set[int] = context.bot_data["allowed_users"]
    if not _is_allowed(update, allowed_users):
        return

    if update.message is None:
        return

    project = await _require_project(update, context.bot_data)
    if project is None:
        return

    config_signals = project.config_signals
    names = sorted(config_signals)
    if names:
        lines: list[str] = []
        for name in names:
            lines.append(f"  {name}")
            sig = config_signals[name]
            for field_name, field_cfg in sig.payload.items():
                if field_name == "sender":
                    continue
                req = ", required" if field_cfg.required else ""
                lines.append(f"    {field_name} ({field_cfg.field_type}{req})")
        listing = "\n".join(lines)
        header = f"[{project.name}] Available signals:" if len(context.bot_data["projects"]) > 1 else "Available signals:"
        await update.message.reply_text(f"{header}\n{listing}")
    else:
        await update.message.reply_text("No signals configured.")


async def handle_logs(update, context) -> None:
    """Handle the ``/logs`` command: show recent log output."""
    from propagate_app.log_buffer import get_recent_logs

    allowed_users: set[int] = context.bot_data["allowed_users"]
    if not _is_allowed(update, allowed_users):
        return

    if update.message is None:
        return

    text: str = update.message.text
    parts = text.strip().split()
    n = 20
    if len(parts) > 1:
        try:
            n = int(parts[1])
        except ValueError:
            await update.message.reply_text("Usage: /logs [N] — N must be a number.")
            return

    lines = get_recent_logs(n)
    if not lines:
        await update.message.reply_text("No logs available.")
        return

    while lines:
        body = "\n".join(lines)
        if len(body) <= 4096:
            break
        lines.pop(0)
    await update.message.reply_text(body)


async def handle_help(update, context) -> None:
    """Handle the ``/help`` command."""
    allowed_users: set[int] = context.bot_data["allowed_users"]
    if not _is_allowed(update, allowed_users):
        return

    if update.message is None:
        return

    project = _resolve_project(context.bot_data, update.message.chat_id)
    if project is not None:
        config_signals = project.config_signals
    else:
        config_signals = {}
        for p in context.bot_data["projects"].values():
            config_signals.update(p.config_signals)
    names = sorted(config_signals)
    signals_line = ", ".join(names) if names else "(none)"
    project_line = ""
    if len(context.bot_data["projects"]) > 1:
        project_line = "/project [name] — list or switch active project\n"
    await update.message.reply_text(
        "Commands:\n"
        "/signal <signal> [param:value ...] — send a signal to propagate\n"
        "/resume — resume a failed run\n"
        "/signals — list available signals\n"
        "/logs [N] — show last N log lines (default 20)\n"
        f"{project_line}"
        "/list — list loaded projects\n"
        "/unload <name> — stop and unload a project\n"
        "/reload <name> — reload a project\n"
        "/help — show this message\n"
        f"\nAvailable signals: {signals_line}"
    )


async def _wait_for_response(bot_data: dict[str, Any], request_id: str, timeout: float = 10.0) -> dict | None:
    """Wait for a coordinator_response matching request_id."""
    response_queue: asyncio.Queue[dict] = bot_data["response_queue"]
    stashed: list[dict] = []
    loop = asyncio.get_running_loop()
    try:
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                event = await asyncio.wait_for(response_queue.get(), timeout=remaining)
            except TimeoutError:
                return None
            if event.get("request_id") == request_id:
                return event
            stashed.append(event)
    finally:
        for item in stashed:
            await response_queue.put(item)


def _refresh_bot_projects(bot_data: dict[str, Any], project_list: list[dict]) -> None:
    """Update the bot's project cache from a coordinator list response."""
    from propagate_app.signal_transport import parse_signals_from_coordinator

    projects: dict[str, ProjectState] = bot_data["projects"]
    new_projects: dict[str, ProjectState] = {}
    for proj_info in project_list:
        name = proj_info["name"]
        config_signals = parse_signals_from_coordinator(proj_info.get("signals", {}))
        if name in projects:
            existing = projects[name]
            existing.config_signals = config_signals
            new_projects[name] = existing
        else:
            new_projects[name] = ProjectState(name=name, config_signals=config_signals)
    bot_data["projects"] = new_projects
    active: dict[int, str] = bot_data["active_project"]
    for chat_id in list(active):
        if active[chat_id] not in new_projects:
            del active[chat_id]


async def handle_list(update, context) -> None:
    """Handle the ``/list`` command: list loaded projects from coordinator."""
    import uuid

    bot_data: dict[str, Any] = context.bot_data
    if not _is_allowed(update, bot_data["allowed_users"]):
        return
    if update.message is None:
        return

    push_socket = bot_data["push_socket"]
    request_id = str(uuid.uuid4())
    send_coordinator_command(push_socket, "list", metadata={"request_id": request_id})
    resp = await _wait_for_response(bot_data, request_id)
    if resp is None:
        await update.message.reply_text("No response from coordinator (timeout).")
        return
    if "error" in resp:
        await update.message.reply_text(f"Error: {resp['error']}")
        return

    project_list = resp.get("data", {}).get("projects", [])
    _refresh_bot_projects(bot_data, project_list)

    if not project_list:
        await update.message.reply_text("No projects loaded.")
        return

    chat_id = update.message.chat_id
    current = bot_data["active_project"].get(chat_id)
    lines: list[str] = []
    for proj in project_list:
        marker = " (active)" if proj["name"] == current else ""
        sig_names = ", ".join(sorted(proj.get("signals", {}))) or "(none)"
        lines.append(f"  {proj['name']} [{proj['status']}]{marker} — signals: {sig_names}")
    await update.message.reply_text("Projects:\n" + "\n".join(lines))


async def handle_unload(update, context) -> None:
    """Handle the ``/unload`` command: stop and unload a project."""
    import uuid

    bot_data: dict[str, Any] = context.bot_data
    if not _is_allowed(update, bot_data["allowed_users"]):
        return
    if update.message is None:
        return

    push_socket = bot_data["push_socket"]
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("Usage: /unload <project>")
        return
    name = parts[1]

    request_id = str(uuid.uuid4())
    send_coordinator_command(push_socket, "unload", metadata={"request_id": request_id}, project=name)
    resp = await _wait_for_response(bot_data, request_id)
    if resp is None:
        await update.message.reply_text("No response from coordinator (timeout).")
        return
    if "error" in resp:
        await update.message.reply_text(f"Error: {resp['error']}")
        return

    # Refresh cache.
    request_id2 = str(uuid.uuid4())
    send_coordinator_command(push_socket, "list", metadata={"request_id": request_id2})
    resp2 = await _wait_for_response(bot_data, request_id2, timeout=5.0)
    if resp2 is not None and "error" not in resp2:
        _refresh_bot_projects(bot_data, resp2.get("data", {}).get("projects", []))

    await update.message.reply_text(f"Unloaded project '{name}'.")


async def handle_reload(update, context) -> None:
    """Handle the ``/reload`` command: reload a project."""
    import uuid

    bot_data: dict[str, Any] = context.bot_data
    if not _is_allowed(update, bot_data["allowed_users"]):
        return
    if update.message is None:
        return

    push_socket = bot_data["push_socket"]
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("Usage: /reload <project>")
        return
    name = parts[1]

    request_id = str(uuid.uuid4())
    send_coordinator_command(push_socket, "reload", metadata={"request_id": request_id}, project=name)
    resp = await _wait_for_response(bot_data, request_id)
    if resp is None:
        await update.message.reply_text("No response from coordinator (timeout).")
        return
    if "error" in resp:
        await update.message.reply_text(f"Error: {resp['error']}")
        return

    # Refresh cache.
    request_id2 = str(uuid.uuid4())
    send_coordinator_command(push_socket, "list", metadata={"request_id": request_id2})
    resp2 = await _wait_for_response(bot_data, request_id2, timeout=5.0)
    if resp2 is not None and "error" not in resp2:
        _refresh_bot_projects(bot_data, resp2.get("data", {}).get("projects", []))

    await update.message.reply_text(f"Reloaded project '{name}'.")


async def _handle_unknown_command(update, context) -> None:
    """Reply to unrecognised commands."""
    if update.message is None:
        return
    if not _is_allowed(update, context.bot_data["allowed_users"]):
        return
    cmd = update.message.text.strip().split()[0]
    await update.message.reply_text(f"Unknown command: {cmd}. Use /help to see available commands.")


async def _poll_events(application, sub_socket) -> None:
    """Background task that polls the SUB socket and sends replies."""
    from propagate_app.log_buffer import append_line

    response_queue: asyncio.Queue[dict] = application.bot_data["response_queue"]
    notify_chats: set[int] = application.bot_data.get("notify_chats", set())
    loop = asyncio.get_running_loop()
    while True:
        event = await loop.run_in_executor(None, lambda: receive_event(sub_socket, timeout_ms=1000))
        if event is None:
            continue
        if event.get("event") == "log":
            line = event.get("line", "")
            append_line(line)
            continue
        if event.get("event") == "coordinator_response":
            await response_queue.put(event)
            continue
        metadata = event.get("metadata") or {}
        chat_id = metadata.get("chat_id")
        origin_chat_id = int(chat_id) if chat_id is not None else None
        if chat_id is None and not (event.get("event") in _TELEGRAM_NOTIFY_EVENTS and notify_chats):
            logger.debug("Received event without chat_id metadata; skipping reply.")
            continue
        message_id = metadata.get("message_id")
        text = format_event_reply(event)
        display_project = event.get("project")
        if display_project is not None:
            text = f"[{display_project}] {text}"
        target_chats: list[int] = []
        if origin_chat_id is not None:
            target_chats.append(origin_chat_id)
        if event.get("event") in _TELEGRAM_NOTIFY_EVENTS:
            for notify_chat_id in sorted(notify_chats):
                if notify_chat_id not in target_chats:
                    target_chats.append(notify_chat_id)

        for target_chat_id in target_chats:
            try:
                kwargs: dict[str, Any] = {"chat_id": target_chat_id, "text": text}
                if message_id is not None and origin_chat_id is not None and target_chat_id == origin_chat_id:
                    kwargs["reply_to_message_id"] = int(message_id)
                await application.bot.send_message(**kwargs)
                logger.debug("Sent event reply to chat %s.", target_chat_id)
            except Exception:
                logger.exception("Failed to send event reply to chat %s.", target_chat_id)


def run_bot(
    projects: dict[str, ProjectState],
    token: str,
    allowed_users: set[int],
    notify_chats: set[int],
) -> None:
    """Start the Telegram bot with long-polling."""
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

    async def post_init(application) -> None:
        push_socket = connect_push_socket(COORDINATOR_ADDRESS)
        sub_socket = connect_sub_socket(COORDINATOR_PUB_ADDRESS)
        application.bot_data["push_socket"] = push_socket
        application.bot_data["sub_socket"] = sub_socket
        logger.info("Connected to coordinator at %s", COORDINATOR_ADDRESS)
        application.bot_data["event_task"] = asyncio.create_task(
            _poll_events(application, sub_socket)
        )

    async def post_shutdown(application) -> None:
        event_task = application.bot_data.get("event_task")
        if event_task is not None:
            event_task.cancel()
            try:
                await event_task
            except asyncio.CancelledError:
                pass
        sub_socket = application.bot_data.get("sub_socket")
        if sub_socket is not None:
            close_sub_socket(sub_socket)
        push_socket = application.bot_data.get("push_socket")
        if push_socket is not None:
            close_push_socket(push_socket)
        logger.info("Disconnected from coordinator.")

    application = ApplicationBuilder().token(token).post_init(post_init).post_shutdown(post_shutdown).build()
    application.bot_data["projects"] = projects
    application.bot_data["active_project"] = {}
    application.bot_data["allowed_users"] = allowed_users
    application.bot_data["notify_chats"] = notify_chats
    application.bot_data["response_queue"] = asyncio.Queue()

    application.add_handler(CommandHandler("project", handle_project))
    application.add_handler(CommandHandler("signal", handle_signal))
    application.add_handler(CommandHandler("resume", handle_resume))
    application.add_handler(CommandHandler("signals", handle_signals))
    application.add_handler(CommandHandler("logs", handle_logs))
    application.add_handler(CommandHandler("list", handle_list))
    application.add_handler(CommandHandler("unload", handle_unload))
    application.add_handler(CommandHandler("reload", handle_reload))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(MessageHandler(filters.COMMAND, _handle_unknown_command))

    logger.info("Starting Telegram bot (allowed users: %s).", ", ".join(str(u) for u in sorted(allowed_users)))
    application.run_polling()
