from __future__ import annotations

import re

from propagate_app.message_parser import build_payload, parse_payload_params, validate_and_build_payload  # noqa: F401


def parse_signal_message(text: str) -> tuple[str, str] | None:
    """Parse a ``/signal`` Telegram message into a signal type and remaining text.

    Handles the ``@BotName`` suffix that Telegram appends in group chats
    (e.g. ``/signal@MyBot deploy``).

    Returns ``(signal_type, remaining_text)`` or ``None`` when no signal type
    can be determined.
    """
    stripped = re.sub(r"^/signal(?:@\S+)?\s*", "", text)
    if not stripped:
        return None

    first_line, _, rest = stripped.partition("\n")
    parts = first_line.split(None, 1)
    signal_type = parts[0]

    # Collect remaining text from remainder of first line + subsequent lines.
    fragments: list[str] = []
    if len(parts) > 1:
        fragments.append(parts[1])
    if rest:
        fragments.append(rest)

    remaining = "\n".join(fragments).strip()
    return signal_type, remaining
