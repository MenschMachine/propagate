from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from propagate_app.errors import PropagateError

logger = logging.getLogger("propagate.telegram")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="propagate-telegram", description="Telegram bot bridge for propagate.")
    parser.add_argument("--config", required=True, help="Path to the propagate YAML config.")
    parser.add_argument("--token", help="Telegram bot token.")
    parser.add_argument("--token-env", help="Environment variable name containing the bot token.")
    parser.add_argument("--allowed-users", required=True, help="Comma-separated Telegram user IDs allowed to send commands.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s")

    try:
        token = _resolve_token(args.token, args.token_env)
    except PropagateError as error:
        logger.error("%s", error)
        return 1

    try:
        allowed_users = _parse_allowed_users(args.allowed_users)
    except PropagateError as error:
        logger.error("%s", error)
        return 1

    config_path = Path(args.config).expanduser().resolve()

    try:
        from propagate_app.config_load import load_config
        from propagate_app.signal_transport import socket_address

        config = load_config(config_path)
        zmq_address = socket_address(config.config_path)
    except Exception as error:
        logger.error("Failed to load config: %s", error)
        return 1

    signal_names = sorted(config.signals)
    logger.info("Loaded %d signal(s): %s", len(signal_names), ", ".join(signal_names))

    from .bot import run_bot

    run_bot(
        config_signals=config.signals,
        zmq_address=zmq_address,
        token=token,
        allowed_users=allowed_users,
    )
    return 0


def _resolve_token(token: str | None, token_env: str | None) -> str:
    if token is not None and token_env is not None:
        raise PropagateError("Cannot specify both --token and --token-env.")
    if token_env is not None:
        value = os.environ.get(token_env)
        if value is None:
            raise PropagateError(f"Environment variable '{token_env}' is not set.")
        return value
    if token is not None:
        return token
    raise PropagateError("Must specify --token or --token-env.")


def _parse_allowed_users(raw: str) -> set[int]:
    try:
        return {int(uid.strip()) for uid in raw.split(",") if uid.strip()}
    except ValueError as error:
        raise PropagateError(f"Invalid user ID in --allowed-users: {error}") from error
