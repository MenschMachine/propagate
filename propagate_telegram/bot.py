from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import zmq

from propagate_app.event_format import format_event_reply
from propagate_app.message_parser import validate_and_build_payload
from propagate_app.signal_transport import (
    close_push_socket,
    close_sub_socket,
    connect_push_socket,
    connect_sub_socket,
    receive_event,
    send_command,
    send_signal,
)

from .message_parser import parse_signal_message

logger = logging.getLogger("propagate.telegram")


@dataclass
class ProjectState:
    name: str
    config_signals: dict[str, Any]
    zmq_address: str
    pub_address: str
    push_socket: zmq.Socket | None = None
    sub_socket: zmq.Socket | None = None
    event_task: asyncio.Task | None = None


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
        # List projects
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
        "chat_id": str(update.message.chat_id),
        "message_id": str(update.message.message_id),
    }
    send_signal(project.push_socket, signal_type, payload, metadata=metadata)
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
        "chat_id": str(update.message.chat_id),
        "message_id": str(update.message.message_id),
    }
    send_command(project.push_socket, "resume", metadata=metadata)
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
        # Merge all signals for help display
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
        "/help — show this message\n"
        f"\nAvailable signals: {signals_line}"
    )


async def _poll_events(application, sub_socket, project_name: str | None = None) -> None:
    """Background task that polls the SUB socket and sends replies."""
    from propagate_app.log_buffer import append_line

    loop = asyncio.get_running_loop()
    while True:
        event = await loop.run_in_executor(None, lambda: receive_event(sub_socket, timeout_ms=1000))
        if event is None:
            continue
        if event.get("event") == "log":
            line = event.get("line", "")
            append_line(line)
            continue
        metadata = event.get("metadata") or {}
        chat_id = metadata.get("chat_id")
        if chat_id is None:
            logger.debug("Received event without chat_id metadata; skipping reply.")
            continue
        message_id = metadata.get("message_id")
        text = format_event_reply(event)
        if project_name is not None:
            text = f"[{project_name}] {text}"
        try:
            kwargs: dict[str, Any] = {"chat_id": int(chat_id), "text": text}
            if message_id is not None:
                kwargs["reply_to_message_id"] = int(message_id)
            await application.bot.send_message(**kwargs)
            logger.debug("Sent event reply to chat %s.", chat_id)
        except Exception:
            logger.exception("Failed to send event reply to chat %s.", chat_id)


def run_bot(
    projects: dict[str, ProjectState],
    token: str,
    allowed_users: set[int],
) -> None:
    """Start the Telegram bot with long-polling."""
    from telegram.ext import ApplicationBuilder, CommandHandler

    multi = len(projects) > 1

    async def post_init(application) -> None:
        for name, project in projects.items():
            project.push_socket = connect_push_socket(project.zmq_address)
            logger.info("Connected to propagate '%s' at %s", name, project.zmq_address)
            if project.pub_address is not None:
                project.sub_socket = connect_sub_socket(project.pub_address)
                prefix = name if multi else None
                project.event_task = asyncio.create_task(
                    _poll_events(application, project.sub_socket, project_name=prefix)
                )
                logger.info("Subscribed to events for '%s' on %s", name, project.pub_address)

    async def post_shutdown(application) -> None:
        for project in projects.values():
            if project.event_task is not None:
                project.event_task.cancel()
                try:
                    await project.event_task
                except asyncio.CancelledError:
                    pass
            if project.sub_socket is not None:
                close_sub_socket(project.sub_socket)
            if project.push_socket is not None:
                close_push_socket(project.push_socket)
        logger.info("Disconnected from all projects.")

    application = ApplicationBuilder().token(token).post_init(post_init).post_shutdown(post_shutdown).build()
    application.bot_data["projects"] = projects
    application.bot_data["active_project"] = {}
    application.bot_data["allowed_users"] = allowed_users

    application.add_handler(CommandHandler("project", handle_project))
    application.add_handler(CommandHandler("signal", handle_signal))
    application.add_handler(CommandHandler("resume", handle_resume))
    application.add_handler(CommandHandler("signals", handle_signals))
    application.add_handler(CommandHandler("logs", handle_logs))
    application.add_handler(CommandHandler("help", handle_help))

    logger.info("Starting Telegram bot (allowed users: %s).", ", ".join(str(u) for u in sorted(allowed_users)))
    application.run_polling()
