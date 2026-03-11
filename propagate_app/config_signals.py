from typing import Any

from .constants import SUPPORTED_SIGNAL_FIELD_TYPES
from .errors import PropagateError
from .models import SignalConfig, SignalFieldConfig
from .validation import (
    validate_allowed_keys,
    validate_context_source_name,
    validate_signal_field_name,
)


def parse_signal_configs(signals_data: Any) -> dict[str, SignalConfig]:
    if signals_data is None:
        return {}
    if not isinstance(signals_data, dict) or not signals_data:
        raise PropagateError("Config 'signals' must be a non-empty mapping when provided.")
    return {
        validate_context_source_name(signal_name): parse_signal_config(
            validate_context_source_name(signal_name),
            signal_data,
        )
        for signal_name, signal_data in signals_data.items()
    }


def parse_signal_config(signal_name: str, signal_data: Any) -> SignalConfig:
    if not isinstance(signal_data, dict):
        raise PropagateError(f"Signal '{signal_name}' must be a mapping.")
    validate_allowed_keys(signal_data, {"payload"}, f"Signal '{signal_name}'")
    payload_data = signal_data.get("payload")
    if not isinstance(payload_data, dict):
        raise PropagateError(f"Signal '{signal_name}' must define a 'payload' mapping.")
    payload = {
        validate_signal_field_name(field_name): parse_signal_field_config(
            signal_name,
            validate_signal_field_name(field_name),
            field_data,
        )
        for field_name, field_data in payload_data.items()
    }
    return SignalConfig(name=signal_name, payload=payload)


def parse_signal_field_config(signal_name: str, field_name: str, field_data: Any) -> SignalFieldConfig:
    location = f"Signal '{signal_name}' payload field '{field_name}'"
    if not isinstance(field_data, dict):
        raise PropagateError(f"{location} must be a mapping.")
    validate_allowed_keys(field_data, {"type", "required"}, location)
    field_type = field_data.get("type", "string")
    if not isinstance(field_type, str) or field_type not in SUPPORTED_SIGNAL_FIELD_TYPES:
        supported_types = ", ".join(sorted(SUPPORTED_SIGNAL_FIELD_TYPES))
        raise PropagateError(f"{location}.type must be one of: {supported_types}.")
    required = field_data.get("required", False)
    if not isinstance(required, bool):
        raise PropagateError(f"{location}.required must be a boolean when provided.")
    return SignalFieldConfig(field_type=field_type, required=required)
