from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from propagate_app.constants import configure_logging
from propagate_app.errors import PropagateError

logger = logging.getLogger("propagate.telegram")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="propagate-telegram", description="Telegram bot bridge for propagate.")
    parser.add_argument("--config", action="append", default=[], help="Path to a propagate YAML config (repeatable). If omitted, connects to coordinator.")
    parser.add_argument("--token", help="Telegram bot token.")
    parser.add_argument("--token-env", help="Environment variable name containing the bot token.")
    parser.add_argument("--allowed-users", help="Comma-separated Telegram user IDs allowed to send commands (default: $TELEGRAM_USERS).")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        token = _resolve_token(args.token, args.token_env)
    except PropagateError as error:
        logger.error("%s", error)
        return 1

    raw_users = _resolve_allowed_users(args.allowed_users)
    if raw_users is None:
        logger.error("Must specify --allowed-users or set TELEGRAM_USERS env var.")
        return 1

    try:
        allowed_users = _parse_allowed_users(raw_users)
    except PropagateError as error:
        logger.error("%s", error)
        return 1

    from .bot import ProjectState, run_bot

    config_values = args.config or []

    if not config_values:
        # Coordinator mode: discover projects at startup via list command.
        projects = _discover_projects_from_coordinator()
        if projects is None:
            logger.error("Failed to discover projects from coordinator.")
            return 1
        run_bot(
            projects=projects,
            token=token,
            allowed_users=allowed_users,
            coordinator_mode=True,
        )
        return 0

    # Legacy mode: load configs directly.
    from propagate_app.config_load import load_config
    from propagate_app.signal_transport import pub_socket_address, socket_address

    projects: dict[str, ProjectState] = {}
    for config_value in config_values:
        config_path = Path(config_value).expanduser().resolve()
        try:
            config = load_config(config_path)
            zmq_address = socket_address(config.config_path)
            pub_address = pub_socket_address(config.config_path)
        except Exception as error:
            logger.error("Failed to load config '%s': %s", config_value, error)
            return 1

        name = config_path.stem
        if name in projects:
            logger.error("Duplicate config name '%s' from '%s'. Config filenames must be unique.", name, config_value)
            return 1
        signal_names = sorted(config.signals)
        logger.info("[%s] Loaded %d signal(s): %s", name, len(signal_names), ", ".join(signal_names))
        projects[name] = ProjectState(
            name=name,
            config_signals=config.signals,
            zmq_address=zmq_address,
            pub_address=pub_address,
        )

    run_bot(
        projects=projects,
        token=token,
        allowed_users=allowed_users,
    )
    return 0


def _discover_projects_from_coordinator() -> dict | None:
    """Send a list command to the coordinator and build ProjectState objects."""
    import uuid

    from propagate_app.signal_transport import (
        COORDINATOR_ADDRESS,
        COORDINATOR_PUB_ADDRESS,
        close_push_socket,
        close_sub_socket,
        connect_push_socket,
        connect_sub_socket,
        receive_event,
        send_coordinator_command,
    )

    push = connect_push_socket(COORDINATOR_ADDRESS)
    sub = connect_sub_socket(COORDINATOR_PUB_ADDRESS)
    try:
        import time
        # Retry to handle the ZMQ slow-joiner problem: the SUB may miss
        # the first response because it hasn't finished connecting yet.
        for attempt in range(3):
            request_id = str(uuid.uuid4())
            send_coordinator_command(push, "list", metadata={"request_id": request_id})
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms <= 0:
                    break
                event = receive_event(sub, timeout_ms=min(remaining_ms, 500))
                if event is None:
                    continue
                if event.get("event") == "coordinator_response" and event.get("request_id") == request_id:
                    return _parse_project_list(event)
            logger.debug("Discovery attempt %d/3 timed out, retrying.", attempt + 1)
        logger.error("Timeout waiting for coordinator list response.")
        return None
    finally:
        close_push_socket(push)
        close_sub_socket(sub)


def _parse_project_list(event: dict) -> dict:
    from propagate_app.models import SignalConfig, SignalFieldConfig

    from .bot import ProjectState

    data = event.get("data", {})
    projects: dict[str, ProjectState] = {}
    for proj_info in data.get("projects", []):
        name = proj_info["name"]
        config_signals: dict[str, SignalConfig] = {}
        for sig_name, sig_data in proj_info.get("signals", {}).items():
            payload_fields = {}
            for fname, finfo in sig_data.get("payload", {}).items():
                payload_fields[fname] = SignalFieldConfig(
                    field_type=finfo.get("field_type", "string"),
                    required=finfo.get("required", False),
                )
            config_signals[sig_name] = SignalConfig(name=sig_name, payload=payload_fields)
        projects[name] = ProjectState(name=name, config_signals=config_signals)
        sig_names = sorted(config_signals)
        logger.info("[%s] Discovered %d signal(s): %s", name, len(sig_names), ", ".join(sig_names))
    return projects


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


def _resolve_allowed_users(cli_value: str | None) -> str | None:
    if cli_value is not None:
        return cli_value
    return os.environ.get("TELEGRAM_USERS")


def _parse_allowed_users(raw: str) -> set[int]:
    try:
        return {int(uid.strip()) for uid in raw.split(",") if uid.strip()}
    except ValueError as error:
        raise PropagateError(f"Invalid user ID in --allowed-users: {error}") from error
