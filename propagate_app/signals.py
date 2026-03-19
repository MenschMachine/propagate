from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .constants import LOGGER
from .context_store import get_context_root, get_execution_context_dir, read_optional_context_value
from .errors import PropagateError
from .models import ActiveSignal, Config, ExecutionConfig, SignalConfig
from .validation import validate_allowed_keys, validate_context_key, validate_context_source_name

_CONTEXT_WHEN_OPERATOR = "equals_context"


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


def validate_signal_when_clause(when: dict[str, Any], signal_config: SignalConfig, location: str, when_label: str) -> None:
    unknown_keys = sorted(set(when) - set(signal_config.payload))
    if unknown_keys:
        raise PropagateError(
            f"{location} {when_label} references unknown payload field '{unknown_keys[0]}'."
            f" Signal '{signal_config.name}' declares: {', '.join(sorted(signal_config.payload))}."
        )
    for field_name, expected_value in when.items():
        field_config = signal_config.payload[field_name]
        if not isinstance(expected_value, dict):
            continue
        if field_config.field_type == "mapping" and not _is_context_when_matcher(expected_value):
            continue
        matcher_location = f"{location} {when_label} field '{field_name}'"
        if not expected_value:
            raise PropagateError(f"{matcher_location} must not be an empty mapping.")
        validate_allowed_keys(expected_value, {_CONTEXT_WHEN_OPERATOR}, matcher_location)
        context_key = validate_context_key(expected_value[_CONTEXT_WHEN_OPERATOR])
        if not context_key.startswith(":"):
            raise PropagateError(f"{matcher_location} '{_CONTEXT_WHEN_OPERATOR}' must use a reserved ':'-prefixed context key.")


def signal_payload_matches_when(
    payload: dict[str, Any],
    when: dict[str, Any] | None,
    context_dir: Path | None = None,
    signal_config: SignalConfig | None = None,
) -> bool:
    if when is None:
        return True
    for key, expected_value in when.items():
        if key not in payload:
            return False
        payload_value = payload[key]
        if _is_context_when_matcher(expected_value):
            if signal_config is None:
                raise PropagateError("Context-aware signal matching requires a signal config.")
            resolved_value = _resolve_context_when_field_value(
                expected_value,
                signal_config.payload[key].field_type,
                context_dir,
            )
            if resolved_value is _UNPARSEABLE_CONTEXT_VALUE:
                return False
            if payload_value != resolved_value:
                return False
            continue
        if payload_value != expected_value:
            return False
    return True


def resolve_signal_when_payload(
    when: dict[str, Any] | None,
    signal_config: SignalConfig,
    context_dir: Path | None = None,
) -> dict[str, Any] | None:
    if when is None:
        return None
    resolved: dict[str, Any] = {}
    for field_name, expected_value in when.items():
        if not _is_context_when_matcher(expected_value):
            resolved[field_name] = expected_value
            continue
        context_value = _resolve_context_when_value(expected_value, context_dir)
        if context_value in {None, ""}:
            return None
        resolved_value = _deserialize_context_value(context_value, signal_config.payload[field_name].field_type)
        if resolved_value is _UNPARSEABLE_CONTEXT_VALUE:
            return None
        resolved[field_name] = resolved_value
    return resolved


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
        ensure_execution_accepts_signal(
            execution,
            active_signal,
            _execution_context_dir(config, execution.name),
            config.signals.get(active_signal.signal_type) if active_signal is not None else None,
        )
        return execution
    if active_signal is not None:
        active_signal_config = config.signals[active_signal.signal_type]
        matching_executions = [
            execution for execution in config.executions.values()
            if any(
                es.signal_name == active_signal.signal_type
                and signal_payload_matches_when(
                    active_signal.payload,
                    es.when,
                    _execution_context_dir(config, execution.name),
                    active_signal_config,
                )
                for es in execution.signals
            )
        ]
        if not matching_executions:
            raise PropagateError(f"No execution accepts signal '{active_signal.signal_type}'.")
        if len(matching_executions) > 1:
            names = ", ".join(e.name for e in matching_executions)
            raise PropagateError(
                f"Multiple executions accept signal '{active_signal.signal_type}'"
                f" with the given payload: {names}. Specify --execution or narrow 'when' filters."
            )
        execution = matching_executions[0]
        LOGGER.info("Auto-selected execution '%s' for signal '%s'.", execution.name, active_signal.signal_type)
        return execution
    execution = select_execution(config, None)
    ensure_execution_accepts_signal(
        execution,
        active_signal,
        _execution_context_dir(config, execution.name),
        config.signals.get(active_signal.signal_type) if active_signal is not None else None,
    )
    return execution


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


def ensure_execution_accepts_signal(
    execution: ExecutionConfig,
    active_signal: ActiveSignal | None,
    context_dir: Path | None = None,
    signal_config: SignalConfig | None = None,
) -> None:
    if not execution.signals:
        return
    if active_signal is not None and any(
        es.signal_name == active_signal.signal_type
        and signal_payload_matches_when(active_signal.payload, es.when, context_dir, signal_config)
        for es in execution.signals
    ):
        return
    signal_names = [es.signal_name for es in execution.signals]
    if active_signal is None:
        raise PropagateError(
            f"Execution '{execution.name}' requires a signal. Accepted signals: {', '.join(signal_names)}."
        )
    type_matches = any(es.signal_name == active_signal.signal_type for es in execution.signals)
    if type_matches:
        # If type matched but we got here, a 'when' filter must have rejected the payload —
        # entries without 'when' would have matched unconditionally in the any() above.
        when_clauses = [
            es.when for es in execution.signals
            if es.signal_name == active_signal.signal_type and es.when is not None
        ]
        if when_clauses:
            raise PropagateError(
                f"Execution '{execution.name}' accepts signal '{active_signal.signal_type}'"
                f" but the payload does not match its 'when' filter."
            )
    raise PropagateError(
        f"Execution '{execution.name}' does not accept signal '{active_signal.signal_type}'."
        f" Allowed signals: {', '.join(signal_names)}."
    )


def _execution_context_dir(config: Config, execution_name: str) -> Path:
    return get_execution_context_dir(get_context_root(config.config_path), execution_name)


def _is_context_when_matcher(value: Any) -> bool:
    return isinstance(value, dict) and _CONTEXT_WHEN_OPERATOR in value


def _resolve_context_when_value(expected_value: dict[str, Any], context_dir: Path | None) -> str | None:
    if context_dir is None:
        return None
    return read_optional_context_value(context_dir, expected_value[_CONTEXT_WHEN_OPERATOR])


_UNPARSEABLE_CONTEXT_VALUE = object()


def _deserialize_context_value(raw_value: str, field_type: str) -> Any:
    if field_type == "string":
        return raw_value
    try:
        parsed_value = yaml.safe_load(raw_value)
    except yaml.YAMLError:
        LOGGER.debug("Failed to parse context value %r for signal field type '%s'.", raw_value, field_type)
        return _UNPARSEABLE_CONTEXT_VALUE
    if signal_value_matches_type(parsed_value, field_type):
        return parsed_value
    LOGGER.debug("Context value %r does not match signal field type '%s'.", raw_value, field_type)
    return _UNPARSEABLE_CONTEXT_VALUE


def _resolve_context_when_field_value(
    expected_value: dict[str, Any],
    field_type: str,
    context_dir: Path | None,
) -> Any:
    context_value = _resolve_context_when_value(expected_value, context_dir)
    if context_value in {None, ""}:
        return _UNPARSEABLE_CONTEXT_VALUE
    return _deserialize_context_value(context_value, field_type)
