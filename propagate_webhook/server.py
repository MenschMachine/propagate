from __future__ import annotations

import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from propagate_app.signal_transport import close_push_socket, connect_push_socket, send_signal

from .github_events import parse_github_event

logger = logging.getLogger("propagate.webhook")


def create_app(
    config_signals: dict[str, Any] | None,
    zmq_address: str,
    secret: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            application.state.push_socket = connect_push_socket(zmq_address)
        except Exception:
            logger.exception("Failed to connect to propagate at %s", zmq_address)
            raise
        logger.info("Connected to propagate at %s", zmq_address)
        yield
        if application.state.push_socket is not None:
            close_push_socket(application.state.push_socket)
            application.state.push_socket = None
            logger.info("Disconnected from propagate.")

    app = FastAPI(title="propagate-webhook", lifespan=lifespan)
    app.state.config_signals = config_signals
    app.state.zmq_address = zmq_address
    app.state.secret = secret
    app.state.push_socket = None

    @app.post("/webhook")
    async def webhook(
        request: Request,
        x_github_event: str = Header(..., alias="X-GitHub-Event"),
        x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    ) -> dict[str, str]:
        raw_body = await request.body()

        if app.state.secret is not None:
            _verify_signature(raw_body, x_hub_signature_256, app.state.secret)

        body = await request.json()

        repo = body.get("repository", {}).get("full_name", "unknown")
        sender = body.get("sender", {}).get("login", "unknown")
        logger.info("Webhook received: event=%s repo=%s sender=%s", x_github_event, repo, sender)

        if app.state.secret is not None:
            logger.debug("Signature verified")

        result = parse_github_event(x_github_event, body)
        if result is None:
            logger.info("Unsupported event type '%s'; ignoring.", x_github_event)
            return {"status": "ignored", "reason": "unsupported_event"}

        signal_name, payload = result
        logger.debug("Parsed signal '%s' with payload: %s", signal_name, payload)

        if app.state.config_signals is not None and signal_name not in app.state.config_signals:
            defined = ", ".join(sorted(app.state.config_signals))
            logger.info("Signal '%s' not defined in config (defined: %s); ignoring.", signal_name, defined)
            return {"status": "ignored", "reason": "unknown_signal"}

        if app.state.push_socket is None:
            raise HTTPException(status_code=503, detail="Signal transport not connected.")

        send_signal(app.state.push_socket, signal_name, payload)
        if app.state.config_signals is None:
            logger.info("Forwarded signal '%s' for %s to coordinator.", signal_name, repo)
            return {"status": "forwarded", "signal": signal_name}
        logger.info("Delivered signal '%s' for %s.", signal_name, repo)
        return {"status": "delivered", "signal": signal_name}

    return app


def _verify_signature(body: bytes, signature_header: str | None, secret: str) -> None:
    if signature_header is None:
        raise HTTPException(status_code=403, detail="Missing X-Hub-Signature-256 header.")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=403, detail="Invalid signature.")
