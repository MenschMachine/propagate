from __future__ import annotations

import logging
from typing import Any

from propagate_app.signal_transport import close_push_socket, connect_push_socket, send_command, send_signal

from .message_parser import parse_run_message

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


async def handle_run(update, context) -> None:
    """Handle the ``/run`` command: parse, validate, and deliver a signal."""
    bot_data: dict[str, Any] = context.bot_data
    allowed_users: set[int] = bot_data["allowed_users"]

    if not _is_allowed(update, allowed_users):
        return

    if update.message is None:
        return

    text: str = update.message.text
    result = parse_run_message(text)
    if result is None:
        await update.message.reply_text("Usage: /run <signal> [instructions]")
        return

    signal_type, payload = result
    config_signals: dict[str, Any] = bot_data["config_signals"]

    if signal_type not in config_signals:
        defined = ", ".join(sorted(config_signals))
        await update.message.reply_text(f"Signal '{signal_type}' not defined in config (defined: {defined}).")
        return

    sender = update.effective_user.username or str(update.effective_user.id)
    payload["sender"] = sender

    push_socket = bot_data["push_socket"]
    send_signal(push_socket, signal_type, payload)
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
    send_command(push_socket, "resume")
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
        "/run <signal> [instructions] — send a signal to propagate\n"
        "/resume — resume a failed run\n"
        "/signals — list available signals\n"
        "/help — show this message\n"
        f"\nAvailable signals: {signals_line}"
    )


def run_bot(config_signals: dict[str, Any], zmq_address: str, token: str, allowed_users: set[int]) -> None:
    """Start the Telegram bot with long-polling."""
    from telegram.ext import ApplicationBuilder, CommandHandler

    async def post_init(application) -> None:
        application.bot_data["push_socket"] = connect_push_socket(zmq_address)
        logger.info("Connected to propagate at %s", zmq_address)

    async def post_shutdown(application) -> None:
        socket = application.bot_data.get("push_socket")
        if socket is not None:
            close_push_socket(socket)
            logger.info("Disconnected from propagate.")

    application = ApplicationBuilder().token(token).post_init(post_init).post_shutdown(post_shutdown).build()
    application.bot_data["config_signals"] = config_signals
    application.bot_data["allowed_users"] = allowed_users

    application.add_handler(CommandHandler("run", handle_run))
    application.add_handler(CommandHandler("resume", handle_resume))
    application.add_handler(CommandHandler("signals", handle_signals))
    application.add_handler(CommandHandler("help", handle_help))

    logger.info("Starting Telegram bot (allowed users: %s).", ", ".join(str(u) for u in sorted(allowed_users)))
    application.run_polling()
