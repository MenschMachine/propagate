from __future__ import annotations

from string import Formatter

from .context_store import read_context_value, resolve_context_dir_for_read
from .errors import PropagateError
from .models import RuntimeContext
from .validation import validate_context_key

_FORMATTER = Formatter()


def render_git_template(template: str, runtime_context: RuntimeContext) -> str:
    rendered: list[str] = []
    try:
        for literal_text, field_name, format_spec, conversion in _FORMATTER.parse(template):
            rendered.append(literal_text)
            if field_name is None:
                continue
            if format_spec:
                raise PropagateError(f"Git template field '{field_name}' does not support format specifiers.")
            if conversion:
                raise PropagateError(f"Git template field '{field_name}' does not support conversions.")
            rendered.append(resolve_git_template_field(field_name, runtime_context))
    except ValueError as error:
        raise PropagateError(f"Invalid git template '{template}': {error}") from error
    return "".join(rendered)


def resolve_git_template_field(field_name: str, runtime_context: RuntimeContext) -> str:
    if field_name.startswith("signal[") and field_name.endswith("]"):
        return _resolve_signal_field(field_name[7:-1], runtime_context)
    if field_name.startswith("context["):
        return _resolve_context_field(field_name, runtime_context)
    if field_name == "execution.name":
        return runtime_context.execution_name
    raise PropagateError(
        f"Unsupported git template field '{field_name}'. "
        "Supported forms: {signal[field]}, {context[key]}, {context[scope][key]}, {execution.name}."
    )


def _resolve_signal_field(field_name: str, runtime_context: RuntimeContext) -> str:
    active_signal = runtime_context.active_signal
    if active_signal is None:
        raise PropagateError(f"Git template field 'signal[{field_name}]' requires an active signal.")
    if field_name not in active_signal.payload:
        raise PropagateError(
            f"Git template field 'signal[{field_name}]' was not found in active signal payload."
        )
    value = active_signal.payload[field_name]
    if isinstance(value, (dict, list)):
        raise PropagateError(f"Git template field 'signal[{field_name}]' must resolve to a scalar value.")
    return str(value)


def _resolve_context_field(field_name: str, runtime_context: RuntimeContext) -> str:
    remainder = field_name[7:]
    parts: list[str] = []
    while remainder.startswith("["):
        close_index = remainder.find("]")
        if close_index == -1:
            raise PropagateError(f"Git template field '{field_name}' is missing a closing ']'.")
        parts.append(remainder[1:close_index])
        remainder = remainder[close_index + 1:]
    if remainder:
        raise PropagateError(f"Git template field '{field_name}' has unexpected trailing characters.")
    if len(parts) == 1:
        scope = None
        key = parts[0]
    elif len(parts) == 2:
        scope, key = parts
    else:
        raise PropagateError(
            f"Git template field '{field_name}' must be either context[key] or context[scope][key]."
        )
    if not key:
        raise PropagateError(f"Git template field '{field_name}' must include a non-empty context key.")
    key = validate_context_key(key)
    if scope == "global":
        context_dir = resolve_context_dir_for_read(
            runtime_context.context_root,
            runtime_context.execution_name,
            runtime_context.task_id,
            scope_global=True,
        )
    else:
        context_dir = resolve_context_dir_for_read(
            runtime_context.context_root,
            runtime_context.execution_name,
            runtime_context.task_id,
            scope_task=scope,
        )
    return read_context_value(context_dir, key)
