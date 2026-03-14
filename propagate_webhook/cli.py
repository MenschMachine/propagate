from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from propagate_app.errors import PropagateError

logger = logging.getLogger("propagate.webhook")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="propagate-webhook", description="GitHub webhook listener for propagate.")
    parser.add_argument("--config", required=True, help="Path to the propagate YAML config.")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080).")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0).")
    parser.add_argument("--secret", help="GitHub webhook secret for HMAC-SHA256 verification.")
    parser.add_argument("--secret-env", help="Environment variable name containing the webhook secret.")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        secret = _resolve_secret(args.secret, args.secret_env)
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

    from .server import create_app

    app = create_app(
        config_signals=config.signals,
        zmq_address=zmq_address,
        secret=secret,
    )

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _resolve_secret(secret: str | None, secret_env: str | None) -> str | None:
    if secret is not None and secret_env is not None:
        raise PropagateError("Cannot specify both --secret and --secret-env.")
    if secret_env is not None:
        value = os.environ.get(secret_env)
        if value is None:
            raise PropagateError(f"Environment variable '{secret_env}' is not set.")
        return value
    return secret
