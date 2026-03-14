from __future__ import annotations

import re
from typing import Any


def parse_run_message(text: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a ``/run`` Telegram message into a signal type and payload.

    Handles the ``@BotName`` suffix that Telegram appends in group chats
    (e.g. ``/run@MyBot deploy``).

    Returns ``None`` when no signal type can be determined.
    """
    stripped = re.sub(r"^/run(?:@\S+)?\s*", "", text)
    if not stripped:
        return None

    first_line, _, rest = stripped.partition("\n")
    parts = first_line.split(None, 1)
    signal_type = parts[0]

    # Collect instructions from remainder of first line + subsequent lines.
    fragments: list[str] = []
    if len(parts) > 1:
        fragments.append(parts[1])
    if rest:
        fragments.append(rest)

    instructions = "\n".join(fragments).strip()
    payload: dict[str, Any] = {}
    if instructions:
        payload["instructions"] = instructions
    return signal_type, payload
