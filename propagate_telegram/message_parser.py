from __future__ import annotations

import re
import shlex


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


def build_payload(remaining: str, user_fields: list[str], allowed_fields: set[str]) -> dict[str, str]:
    """Build a signal payload from remaining message text.

    Applies single-param shorthand when there is exactly one user-facing field
    and the text doesn't look like ``key:value`` pairs.  Otherwise parses
    ``key:value`` pairs and validates against *allowed_fields*.

    Returns the payload dict.  Raises :class:`ValueError` on parse or
    validation errors.
    """
    if not remaining:
        return {}

    first_token = remaining.split(None, 1)[0]
    if len(user_fields) == 1 and ":" not in first_token:
        return {user_fields[0]: remaining}

    payload = parse_payload_params(remaining)

    unknown = (set(payload) - allowed_fields) | (set(payload) & {"sender"})
    if unknown:
        raise ValueError(f"Unknown payload field(s): {', '.join(sorted(unknown))}")

    return payload


def parse_payload_params(text: str) -> dict[str, str]:
    """Parse ``key:value`` pairs from *text*.

    Uses :func:`shlex.split` for quote-aware tokenisation, then splits each
    token on the first ``:`` only (so ``url:http://example.com`` works).

    Raises :class:`ValueError` if a token contains no ``:``.
    """
    try:
        tokens = shlex.split(text)
    except ValueError:
        raise ValueError("Unmatched quotes in parameter string")
    result: dict[str, str] = {}
    for token in tokens:
        if ":" not in token:
            raise ValueError(f"Invalid parameter (expected key:value): {token!r}")
        key, _, value = token.partition(":")
        result[key] = value
    return result
