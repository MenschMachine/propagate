from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from propagate_app.constants import configure_logging
from propagate_app.errors import PropagateError

logger = logging.getLogger("propagate.webhook")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="propagate-webhook", description="GitHub webhook listener for propagate.")
    parser.add_argument("--config", default=None, help="Path to a propagate YAML config. If omitted, connects to coordinator.")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080).")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0).")
    parser.add_argument("--secret", help="GitHub webhook secret for HMAC-SHA256 verification.")
    parser.add_argument("--secret-env", help="Environment variable name containing the webhook secret.")
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
        secret = _resolve_secret(args.secret, args.secret_env)
    except PropagateError as error:
        logger.error("%s", error)
        return 1

    if args.config:
        return _run_legacy_mode(args, secret)
    return _run_coordinator_mode(args, secret)


def _run_coordinator_mode(args: argparse.Namespace, secret: str | None) -> int:
    """Connect to coordinator. No project discovery needed — coordinator routes by repository."""
    from propagate_app.signal_transport import COORDINATOR_ADDRESS

    from .server import create_app

    logger.info("Webhook connecting to coordinator at %s", COORDINATOR_ADDRESS)

    app = create_app(
        config_signals=None,
        zmq_address=COORDINATOR_ADDRESS,
        secret=secret,
    )

    _run_uvicorn(app, args.host, args.port)
    return 0


def _run_legacy_mode(args: argparse.Namespace, secret: str | None) -> int:
    """Connect directly to a config's socket."""
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

    from .server import create_app

    app = create_app(
        config_signals=config.signals,
        zmq_address=zmq_address,
        secret=secret,
    )

    _run_uvicorn(app, args.host, args.port)
    return 0


def _run_uvicorn(app: object, host: str, port: int) -> None:
    import uvicorn

    log_config = uvicorn.config.LOGGING_CONFIG
    fmt = "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    log_config["formatters"]["default"]["fmt"] = fmt
    log_config["formatters"]["default"]["datefmt"] = datefmt
    log_config["formatters"]["access"]["fmt"] = fmt
    log_config["formatters"]["access"]["datefmt"] = datefmt
    uvicorn.run(app, host=host, port=port, log_level="info", log_config=log_config)


def _resolve_secret(secret: str | None, secret_env: str | None) -> str | None:
    if secret is not None and secret_env is not None:
        raise PropagateError("Cannot specify both --secret and --secret-env.")
    if secret_env is not None:
        value = os.environ.get(secret_env)
        if value is None:
            raise PropagateError(f"Environment variable '{secret_env}' is not set.")
        return value
    return secret
