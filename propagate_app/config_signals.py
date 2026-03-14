from pathlib import Path
from typing import Any

import yaml

from .constants import LOGGER, SUPPORTED_SIGNAL_FIELD_TYPES
from .errors import PropagateError
from .models import SignalConfig, SignalFieldConfig
from .validation import (
    validate_allowed_keys,
    validate_context_source_name,
    validate_signal_field_name,
)


def resolve_signal_includes(signals_data: dict, config_dir: Path) -> dict:
    """Pop 'include' key, load referenced files, merge with inline signals."""
    merged = dict(signals_data)
    include = merged.pop("include", None)
    if include is None:
        return merged
    paths = [include] if isinstance(include, str) else include
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise PropagateError("signals.include must be a string or list of strings.")
    for path_str in paths:
        file_path = (config_dir / path_str).resolve()
        if not file_path.exists():
            raise PropagateError(f"Signal include file does not exist: {file_path}")
        LOGGER.debug("Loading signal include: %s", file_path)
        try:
            with file_path.open("r", encoding="utf-8") as handle:
                included = yaml.safe_load(handle)
        except yaml.YAMLError as error:
            raise PropagateError(
                f"Failed to parse signal include file {file_path}: {error}"
            ) from error
        if not isinstance(included, dict):
            raise PropagateError(
                f"Signal include file must be a YAML mapping: {file_path}"
            )
        for key in included:
            if key in merged:
                raise PropagateError(
                    f"Duplicate signal '{key}' from include file {file_path}"
                )
        merged.update(included)
    return merged


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
