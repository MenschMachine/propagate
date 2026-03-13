from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .constants import LOGGER, SIGNAL_NAMESPACE_PREFIX
from .context_store import ensure_context_dir, require_context_dir, resolve_execution_context_dir, write_context_value
from .errors import PropagateError
from .models import ActiveSignal, RuntimeContext


def prepare_signal_context_for_working_dir(runtime_context: RuntimeContext) -> None:
    context_dir = _resolve_signal_context_dir(runtime_context)
    if context_dir in runtime_context.initialized_signal_context_dirs:
        return
    LOGGER.info("Initializing ':signal' context namespace in '%s'.", context_dir)
    clear_signal_context_namespace(context_dir)
    if runtime_context.active_signal is not None:
        LOGGER.info("Populating ':signal' context namespace for signal '%s'.", runtime_context.active_signal.signal_type)
        store_active_signal_context(context_dir, runtime_context.active_signal)
    runtime_context.initialized_signal_context_dirs.add(context_dir)


def _resolve_signal_context_dir(runtime_context: RuntimeContext) -> Path:
    return resolve_execution_context_dir(runtime_context)


def clear_signal_context_namespace(context_dir: Path) -> None:
    if not context_dir.exists():
        return
    require_context_dir(context_dir)
    try:
        entries = list(context_dir.iterdir())
    except OSError as error:
        raise PropagateError(f"Failed to read context directory {context_dir}: {error}") from error
    for entry in entries:
        if entry.name != SIGNAL_NAMESPACE_PREFIX and not entry.name.startswith(f"{SIGNAL_NAMESPACE_PREFIX}."):
            continue
        if not entry.is_file():
            raise PropagateError(f"Context entry '{entry.name}' is not a file in {context_dir}.")
        try:
            entry.unlink()
        except OSError as error:
            raise PropagateError(f"Failed to clear signal context key '{entry.name}' in {context_dir}: {error}") from error


def store_active_signal_context(context_dir: Path, active_signal: ActiveSignal) -> None:
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":signal.type", active_signal.signal_type)
    write_context_value(context_dir, ":signal.source", active_signal.source)
    write_context_value(context_dir, ":signal.payload", yaml.safe_dump(active_signal.payload, sort_keys=True))
    for field_name, field_value in active_signal.payload.items():
        write_context_value(context_dir, f":signal.{field_name}", serialize_signal_context_value(field_value))


def serialize_signal_context_value(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return yaml.safe_dump(value, sort_keys=True)
    return str(value)
