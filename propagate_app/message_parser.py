from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import SignalConfig


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


def validate_and_build_payload(
    remaining: str, signal_config: SignalConfig,
) -> tuple[dict[str, str], list[str]]:
    """Build and validate a signal payload against *signal_config*.

    Returns ``(payload, errors)`` where *errors* is a list of validation
    messages (empty on success).
    """
    user_fields = [k for k in signal_config.payload if k != "sender"]

    try:
        payload = build_payload(remaining, user_fields, set(signal_config.payload))
    except ValueError as exc:
        return {}, [str(exc)]

    missing = [
        k for k in user_fields
        if signal_config.payload[k].required and k not in payload
    ]
    if missing:
        return payload, [f"Missing required field(s): {', '.join(sorted(missing))}"]

    return payload, []
