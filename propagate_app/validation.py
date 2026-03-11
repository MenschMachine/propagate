from typing import Any

from .constants import CONTEXT_KEY_PATTERN, CONTEXT_SOURCE_NAME_PATTERN
from .errors import PropagateError


def validate_allowed_keys(data: dict[str, Any], allowed_keys: set[str], location: str) -> None:
    unknown_keys = sorted(set(data) - allowed_keys)
    if unknown_keys:
        raise PropagateError(f"{location} has unsupported keys: {', '.join(unknown_keys)}")


def optional_non_empty_string(value: Any, location: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PropagateError(f"{location} must be a non-empty string when provided.")
    return value


def validate_context_key(key: Any) -> str:
    if not isinstance(key, str) or not CONTEXT_KEY_PATTERN.fullmatch(key):
        raise PropagateError(f"Invalid context key '{key}'.")
    return key


def validate_context_source_name(source_name: Any) -> str:
    if not isinstance(source_name, str) or not CONTEXT_SOURCE_NAME_PATTERN.fullmatch(source_name):
        raise PropagateError(f"Invalid context source name '{source_name}'.")
    return source_name


def validate_signal_field_name(field_name: Any) -> str:
    validated_name = validate_context_key(field_name)
    if validated_name.startswith(":"):
        raise PropagateError(f"Invalid signal payload field name '{field_name}'.")
    return validated_name
