from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .constants import LOGGER
from .errors import PropagateError
from .models import ActiveSignal, Config, ExecutionConfig, SignalConfig
from .validation import validate_allowed_keys, validate_context_source_name


def parse_active_signal(
    signal_name: str | None,
    signal_payload: str | None,
    signal_file: str | None,
    signal_configs: dict[str, SignalConfig],
) -> ActiveSignal | None:
    if signal_file is not None and (signal_name is not None or signal_payload is not None):
        raise PropagateError("--signal-file cannot be combined with --signal or --signal-payload.")
    if signal_payload is not None and signal_name is None:
        raise PropagateError("--signal-payload requires --signal.")
    if signal_name is None and signal_file is None:
        return None
    if signal_file is not None:
        resolved_signal_path = Path(signal_file).expanduser().resolve()
        signal_type, payload = load_signal_file(resolved_signal_path)
        source = str(resolved_signal_path)
    else:
        signal_type = validate_context_source_name(signal_name)
        payload = parse_signal_payload_mapping(signal_payload if signal_payload is not None else "{}", f"Signal '{signal_type}' payload")
        source = "cli"
    try:
        signal_config = signal_configs[signal_type]
    except KeyError as error:
        raise PropagateError(f"Signal '{signal_type}' is not defined in config.") from error
    validate_signal_payload(signal_config, payload)
    return ActiveSignal(signal_type=signal_type, payload=payload, source=source)


def load_signal_file(signal_path: Path) -> tuple[str, dict[str, Any]]:
    if not signal_path.exists():
        raise PropagateError(f"Signal file does not exist: {signal_path}")
    try:
        with signal_path.open("r", encoding="utf-8") as handle:
            raw_data = yaml.safe_load(handle)
    except OSError as error:
        raise PropagateError(f"Failed to read signal file {signal_path}: {error}") from error
    except yaml.YAMLError as error:
        raise PropagateError(f"Failed to parse signal file {signal_path}: {error}") from error
    if not isinstance(raw_data, dict):
        raise PropagateError(f"Signal file '{signal_path}' must define a mapping with key 'type'.")
    validate_allowed_keys(raw_data, {"type", "payload"}, f"Signal file '{signal_path}'")
    signal_type = raw_data.get("type")
    if not isinstance(signal_type, str) or not signal_type.strip():
        raise PropagateError(f"Signal file '{signal_path}' must define a mapping with key 'type'.")
    payload = raw_data.get("payload", {})
    if not isinstance(payload, dict):
        raise PropagateError(f"Signal file '{signal_path}' payload must be a mapping.")
    return validate_context_source_name(signal_type), payload


def parse_signal_payload_mapping(payload_text: str, location: str) -> dict[str, Any]:
    try:
        parsed_payload = yaml.safe_load(payload_text)
    except yaml.YAMLError as error:
        raise PropagateError(f"Failed to parse {location}: {error}") from error
    if not isinstance(parsed_payload, dict):
        raise PropagateError(f"{location} must be a mapping.")
    return parsed_payload


def validate_signal_payload(signal_config: SignalConfig, payload: dict[str, Any]) -> None:
    unknown_fields = sorted(set(payload) - set(signal_config.payload))
    if unknown_fields:
        raise PropagateError(f"Signal '{signal_config.name}' payload includes unknown field '{unknown_fields[0]}'.")
    for field_name, field_config in signal_config.payload.items():
        if field_config.required and field_name not in payload:
            raise PropagateError(f"Signal '{signal_config.name}' payload is missing required field '{field_name}'.")
    for field_name, value in payload.items():
        field_config = signal_config.payload[field_name]
        if not signal_value_matches_type(value, field_config.field_type):
            raise PropagateError(
                f"Signal '{signal_config.name}' payload field '{field_name}' must be {describe_signal_field_type(field_config.field_type)}."
            )


def signal_value_matches_type(value: Any, field_type: str) -> bool:
    if field_type == "string":
        return isinstance(value, str)
    if field_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "list":
        return isinstance(value, list)
    if field_type == "mapping":
        return isinstance(value, dict)
    return True


def describe_signal_field_type(field_type: str) -> str:
    descriptions = {
        "string": "a string",
        "number": "a number",
        "boolean": "a boolean",
        "list": "a list",
        "mapping": "a mapping",
    }
    return descriptions.get(field_type, "a valid value")


def log_active_signal(active_signal: ActiveSignal | None) -> None:
    if active_signal is None:
        LOGGER.info("No signal supplied for this run.")
        return
    LOGGER.info("Signal supplied for this run: type='%s', source='%s'.", active_signal.signal_type, active_signal.source)


def select_initial_execution(
    config: Config,
    requested_name: str | None,
    active_signal: ActiveSignal | None,
) -> ExecutionConfig:
    if requested_name:
        execution = select_execution(config, requested_name)
        ensure_execution_accepts_signal(execution, active_signal)
        return execution
    if active_signal is not None:
        matching_executions = [execution for execution in config.executions.values() if active_signal.signal_type in execution.signals]
        if not matching_executions:
            raise PropagateError(f"No execution accepts signal '{active_signal.signal_type}'.")
        if len(matching_executions) > 1:
            raise PropagateError(f"Multiple executions accept signal '{active_signal.signal_type}'; specify --execution.")
        execution = matching_executions[0]
        LOGGER.info("Auto-selected execution '%s' for signal '%s'.", execution.name, active_signal.signal_type)
        return execution
    return select_execution(config, None)


def select_execution(config: Config, requested_name: str | None) -> ExecutionConfig:
    if requested_name:
        try:
            return config.executions[requested_name]
        except KeyError as error:
            raise PropagateError(
                f"Execution '{requested_name}' was not found. Available executions: {', '.join(sorted(config.executions))}"
            ) from error
    if len(config.executions) == 1:
        return next(iter(config.executions.values()))
    raise PropagateError(
        f"Config defines multiple executions; specify one with --execution. Available executions: {', '.join(sorted(config.executions))}"
    )


def ensure_execution_accepts_signal(execution: ExecutionConfig, active_signal: ActiveSignal | None) -> None:
    if active_signal is None or not execution.signals or active_signal.signal_type in execution.signals:
        return
    raise PropagateError(
        f"Execution '{execution.name}' does not accept signal '{active_signal.signal_type}'. Allowed signals: {', '.join(execution.signals)}."
    )
