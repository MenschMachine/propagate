from __future__ import annotations

import asyncio
import logging
from typing import Any

from propagate_app.signal_transport import (
    close_push_socket,
    close_sub_socket,
    connect_push_socket,
    connect_sub_socket,
    receive_event,
    send_command,
    send_signal,
)

from .message_parser import build_payload, parse_signal_message

logger = logging.getLogger("propagate.telegram")


def _is_allowed(update, allowed_users: set[int]) -> bool:
    user = update.effective_user
    if user is None:
        return False
    if user.id in allowed_users:
        return True
    username = user.username or str(user.id)
    logger.warning("Unauthorized command from user %s (id=%d).", username, user.id)
    return False


async def handle_signal(update, context) -> None:
    """Handle the ``/signal`` command: parse, validate, and deliver a signal."""
    bot_data: dict[str, Any] = context.bot_data
    allowed_users: set[int] = bot_data["allowed_users"]

    if not _is_allowed(update, allowed_users):
        return

    if update.message is None:
        return

    text: str = update.message.text
    result = parse_signal_message(text)
    if result is None:
        await update.message.reply_text("Usage: /signal <signal> [param:value ...]")
        return

    signal_type, remaining = result
    config_signals: dict[str, Any] = bot_data["config_signals"]

    if signal_type not in config_signals:
        defined = ", ".join(sorted(config_signals))
        await update.message.reply_text(f"Signal '{signal_type}' not defined in config (defined: {defined}).")
        return

    signal_config = config_signals[signal_type]
    user_fields = [k for k in signal_config.payload if k != "sender"]

    try:
        payload = build_payload(remaining, user_fields, set(signal_config.payload))
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    # Check required fields are present.
    missing = [
        k for k in user_fields
        if signal_config.payload[k].required and k not in payload
    ]
    if missing:
        await update.message.reply_text(f"Missing required field(s): {', '.join(sorted(missing))}")
        return

    sender = update.effective_user.username or str(update.effective_user.id)
    payload["sender"] = sender

    push_socket = bot_data["push_socket"]
    metadata = {
        "chat_id": str(update.message.chat_id),
        "message_id": str(update.message.message_id),
    }
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

    push_socket = bot_data["push_socket"]
    metadata = {
        "chat_id": str(update.message.chat_id),
        "message_id": str(update.message.message_id),
    }
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

    config_signals: dict[str, Any] = context.bot_data["config_signals"]
    names = sorted(config_signals)
    if names:
        listing = "\n".join(f"  {n}" for n in names)
        await update.message.reply_text(f"Available signals:\n{listing}")
    else:
        await update.message.reply_text("No signals configured.")


async def handle_help(update, context) -> None:
    """Handle the ``/help`` command."""
    allowed_users: set[int] = context.bot_data["allowed_users"]
    if not _is_allowed(update, allowed_users):
        return

    if update.message is None:
        return

    config_signals: dict[str, Any] = context.bot_data["config_signals"]
    names = sorted(config_signals)
    signals_line = ", ".join(names) if names else "(none)"
    await update.message.reply_text(
        "Commands:\n"
        "/signal <signal> [param:value ...] — send a signal to propagate\n"
        "/resume — resume a failed run\n"
        "/signals — list available signals\n"
        "/help — show this message\n"
        f"\nAvailable signals: {signals_line}"
    )


def _format_event_reply(event: dict) -> str:
    event_type = event.get("event", "unknown")
    signal_type = event.get("signal_type", "unknown")
    messages = event.get("messages") or []
    lines = [f"Run {'completed' if event_type == 'run_completed' else 'failed'} for signal '{signal_type}'."]
    if messages:
        lines.append("")
        for msg in messages:
            lines.append(msg)
    return "\n".join(lines)


async def _poll_events(application, sub_socket) -> None:
    """Background task that polls the SUB socket and sends replies."""
    loop = asyncio.get_running_loop()
    while True:
        event = await loop.run_in_executor(None, lambda: receive_event(sub_socket, timeout_ms=1000))
        if event is None:
            continue
        metadata = event.get("metadata") or {}
        chat_id = metadata.get("chat_id")
        if chat_id is None:
            logger.debug("Received event without chat_id metadata; skipping reply.")
            continue
        message_id = metadata.get("message_id")
        text = _format_event_reply(event)
        try:
            kwargs: dict[str, Any] = {"chat_id": int(chat_id), "text": text}
            if message_id is not None:
                kwargs["reply_to_message_id"] = int(message_id)
            await application.bot.send_message(**kwargs)
            logger.debug("Sent event reply to chat %s.", chat_id)
        except Exception:
            logger.exception("Failed to send event reply to chat %s.", chat_id)


def run_bot(
    config_signals: dict[str, Any],
    zmq_address: str,
    token: str,
    allowed_users: set[int],
    pub_address: str | None = None,
) -> None:
    """Start the Telegram bot with long-polling."""
    from telegram.ext import ApplicationBuilder, CommandHandler

    async def post_init(application) -> None:
        application.bot_data["push_socket"] = connect_push_socket(zmq_address)
        logger.info("Connected to propagate at %s", zmq_address)
        if pub_address is not None:
            sub_socket = connect_sub_socket(pub_address)
            application.bot_data["sub_socket"] = sub_socket
            application.bot_data["event_task"] = asyncio.create_task(_poll_events(application, sub_socket))
            logger.info("Subscribed to events on %s", pub_address)

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
            logger.info("Disconnected from event socket.")
        socket = application.bot_data.get("push_socket")
        if socket is not None:
            close_push_socket(socket)
            logger.info("Disconnected from propagate.")

    application = ApplicationBuilder().token(token).post_init(post_init).post_shutdown(post_shutdown).build()
    application.bot_data["config_signals"] = config_signals
    application.bot_data["allowed_users"] = allowed_users

    application.add_handler(CommandHandler("signal", handle_signal))
    application.add_handler(CommandHandler("resume", handle_resume))
    application.add_handler(CommandHandler("signals", handle_signals))
    application.add_handler(CommandHandler("help", handle_help))

    logger.info("Starting Telegram bot (allowed users: %s).", ", ".join(str(u) for u in sorted(allowed_users)))
    application.run_polling()
