from __future__ import annotations

import collections
import logging


class BufferedLogHandler(logging.Handler):
    """Log handler that keeps the last *maxlen* formatted records in memory."""

    def __init__(self, maxlen: int = 500) -> None:
        super().__init__()
        self.buffer: collections.deque[str] = collections.deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        self.buffer.append(self.format(record))


_buffered_handler: BufferedLogHandler | None = None


def get_recent_logs(n: int = 20) -> list[str]:
    """Return the last *n* log lines from the in-memory buffer."""
    if _buffered_handler is None:
        return []
    items = list(_buffered_handler.buffer)
    return items[-n:] if n < len(items) else items


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
