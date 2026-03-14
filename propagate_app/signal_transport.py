from __future__ import annotations

import hashlib
import os
from pathlib import Path

import zmq

from .constants import LOGGER


def socket_address(config_path: Path) -> str:
    path_hash = hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:16]
    return f"ipc:///tmp/propagate-{path_hash}.sock"


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


def send_signal(socket: zmq.Socket, signal_type: str, payload: dict) -> None:
    socket.send_json({"signal_type": signal_type, "payload": payload})
    LOGGER.debug("Sent signal '%s' with payload %s", signal_type, payload)


def receive_signal(socket: zmq.Socket, *, block: bool = False, timeout_ms: int = 1000) -> tuple[str, dict] | None:
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
    if not isinstance(data, dict) or "signal_type" not in data or "payload" not in data:
        LOGGER.warning("Received malformed signal message; ignoring.")
        return None
    return data["signal_type"], data["payload"]


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


def _unlink_stale_socket(address: str) -> None:
    if address.startswith("ipc://"):
        path = address[len("ipc://"):]
        try:
            os.unlink(path)
            LOGGER.debug("Removed stale socket file %s", path)
        except FileNotFoundError:
            pass
