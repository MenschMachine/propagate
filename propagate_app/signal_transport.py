from __future__ import annotations

import hashlib
import os
from pathlib import Path

import zmq

from .constants import LOGGER


def socket_address(config_path: Path) -> str:
    path_hash = hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:16]
    return f"ipc:///tmp/propagate-{path_hash}.sock"


def pub_socket_address(config_path: Path) -> str:
    path_hash = hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:16]
    return f"ipc:///tmp/propagate-pub-{path_hash}.sock"


def bind_pull_socket(address: str) -> zmq.Socket:
    _unlink_stale_socket(address)
    ctx = zmq.Context()
    socket = ctx.socket(zmq.PULL)
    socket.bind(address)
    LOGGER.debug("Bound PULL socket on %s", address)
    return socket


def connect_push_socket(address: str) -> zmq.Socket:
    ctx = zmq.Context()
    socket = ctx.socket(zmq.PUSH)
    socket.setsockopt(zmq.LINGER, 5000)
    socket.connect(address)
    LOGGER.debug("Connected PUSH socket to %s", address)
    return socket


def send_signal(socket: zmq.Socket, signal_type: str, payload: dict, metadata: dict | None = None) -> None:
    msg: dict = {"signal_type": signal_type, "payload": payload}
    if metadata:
        msg["metadata"] = metadata
    socket.send_json(msg)
    LOGGER.debug("Sent signal '%s' with payload %s", signal_type, payload)


def send_command(socket: zmq.Socket, command: str, metadata: dict | None = None) -> None:
    msg: dict = {"command": command}
    if metadata:
        msg["metadata"] = metadata
    socket.send_json(msg)
    LOGGER.debug("Sent command '%s'", command)


def _recv_json(socket: zmq.Socket, *, block: bool, timeout_ms: int) -> dict | None:
    """Read one JSON object from *socket*, returning ``None`` on timeout."""
    try:
        if block:
            if socket.poll(timeout_ms) == 0:
                return None
            data = socket.recv_json()
        else:
            try:
                data = socket.recv_json(flags=zmq.NOBLOCK)
            except zmq.Again:
                return None
    except (ValueError, KeyError):
        LOGGER.warning("Received non-JSON message; ignoring.")
        return None
    if not isinstance(data, dict):
        LOGGER.warning("Received malformed message; ignoring.")
        return None
    return data


def receive_signal(socket: zmq.Socket, *, block: bool = False, timeout_ms: int = 1000) -> tuple[str, dict] | None:
    """Receive a signal, returning ``(signal_type, payload)``.

    Metadata (if present) is intentionally discarded — callers that need it
    should use :func:`receive_message` instead.
    """
    data = _recv_json(socket, block=block, timeout_ms=timeout_ms)
    if data is None:
        return None
    if "signal_type" not in data or "payload" not in data:
        LOGGER.warning("Received non-signal message; ignoring.")
        return None
    return data["signal_type"], data["payload"]


def receive_message(
    socket: zmq.Socket, *, block: bool = False, timeout_ms: int = 1000
) -> tuple[str, str, dict, dict] | None:
    """Receive a message, returning ``(kind, name, payload, metadata)``.

    *kind* is ``"signal"`` or ``"command"``.  Returns ``None`` on timeout.
    """
    data = _recv_json(socket, block=block, timeout_ms=timeout_ms)
    if data is None:
        return None
    metadata = data.get("metadata") or {}
    if "command" in data and isinstance(data["command"], str):
        return "command", data["command"], {}, metadata
    if "signal_type" in data and "payload" in data:
        return "signal", data["signal_type"], data["payload"], metadata
    LOGGER.warning("Received unrecognised message; ignoring.")
    return None


def close_pull_socket(socket: zmq.Socket, address: str) -> None:
    ctx = socket.context
    socket.close()
    ctx.term()
    _unlink_stale_socket(address)
    LOGGER.debug("Closed PULL socket and cleaned up %s", address)


def close_push_socket(socket: zmq.Socket) -> None:
    ctx = socket.context
    socket.close()
    ctx.term()
    LOGGER.debug("Closed PUSH socket.")


def bind_pub_socket(address: str) -> zmq.Socket:
    _unlink_stale_socket(address)
    ctx = zmq.Context()
    socket = ctx.socket(zmq.PUB)
    socket.bind(address)
    LOGGER.debug("Bound PUB socket on %s", address)
    return socket


def connect_sub_socket(address: str) -> zmq.Socket:
    ctx = zmq.Context()
    socket = ctx.socket(zmq.SUB)
    socket.setsockopt(zmq.SUBSCRIBE, b"")
    socket.connect(address)
    LOGGER.debug("Connected SUB socket to %s", address)
    return socket


def publish_event_if_available(pub_socket: zmq.Socket | None, event_type: str, data: dict) -> None:
    if pub_socket is not None:
        publish_event(pub_socket, event_type, data)


def publish_event(socket: zmq.Socket, event_type: str, data: dict) -> None:
    msg = {"event": event_type, **data}
    socket.send_json(msg)
    LOGGER.debug("Published event '%s'", event_type)


def receive_event(socket: zmq.Socket, timeout_ms: int = 1000) -> dict | None:
    if socket.poll(timeout_ms) == 0:
        return None
    try:
        data = socket.recv_json(flags=zmq.NOBLOCK)
    except zmq.Again:
        return None
    except (ValueError, KeyError):
        LOGGER.warning("Received non-JSON event; ignoring.")
        return None
    if not isinstance(data, dict) or "event" not in data:
        LOGGER.warning("Received malformed event; ignoring.")
        return None
    return data


def close_pub_socket(socket: zmq.Socket, address: str) -> None:
    ctx = socket.context
    socket.close()
    ctx.term()
    _unlink_stale_socket(address)
    LOGGER.debug("Closed PUB socket and cleaned up %s", address)


def close_sub_socket(socket: zmq.Socket) -> None:
    ctx = socket.context
    socket.close()
    ctx.term()
    LOGGER.debug("Closed SUB socket.")


def _unlink_stale_socket(address: str) -> None:
    if address.startswith("ipc://"):
        path = address[len("ipc://"):]
        try:
            os.unlink(path)
            LOGGER.debug("Removed stale socket file %s", path)
        except FileNotFoundError:
            pass
