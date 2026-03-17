from __future__ import annotations

import collections
import logging

import zmq


class BufferedLogHandler(logging.Handler):
    """Log handler that keeps the last *maxlen* formatted records in memory."""

    def __init__(self, maxlen: int = 500) -> None:
        super().__init__()
        self.buffer: collections.deque[str] = collections.deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        self.buffer.append(self.format(record))


class ZmqLogHandler(logging.Handler):
    """Log handler that publishes each record as a JSON event on a ZMQ PUB socket."""

    def __init__(self, socket: zmq.Socket) -> None:
        super().__init__(level=logging.INFO)
        self._socket = socket

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self._socket.send_json({"event": "log", "line": line})
        except Exception:
            self.handleError(record)


_buffered_handler: BufferedLogHandler | None = None


def get_recent_logs(n: int = 20) -> list[str]:
    """Return the last *n* log lines from the in-memory buffer."""
    if _buffered_handler is None:
        return []
    items = list(_buffered_handler.buffer)
    return items[-n:] if n < len(items) else items


def append_line(line: str) -> None:
    """Append a pre-formatted log line directly to the buffered handler."""
    if _buffered_handler is not None:
        _buffered_handler.buffer.append(line)


def install_buffered_handler() -> None:
    """Create and attach the buffered handler to the root logger."""
    global _buffered_handler  # noqa: PLW0603
    _buffered_handler = BufferedLogHandler()
    _buffered_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logging.getLogger().addHandler(_buffered_handler)
