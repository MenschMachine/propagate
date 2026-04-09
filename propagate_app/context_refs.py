from __future__ import annotations

from pathlib import Path
from typing import Any

from .context_store import (
    read_context_value,
    resolve_context_dir_for_read,
    resolve_context_dir_for_write,
    write_context_value,
)
from .errors import PropagateError
from .models import ContextCondition, RuntimeContext, ScopedContextKey
from .validation import validate_allowed_keys, validate_context_key


def parse_scoped_context_key(value: Any, location: str) -> ScopedContextKey:
    if isinstance(value, str):
        validated_key = validate_context_key(value)
        if not validated_key.startswith(":"):
            raise PropagateError(f"{location} must use a reserved ':'-prefixed context key.")
        return ScopedContextKey(key=validated_key)
    if not isinstance(value, dict):
        raise PropagateError(f"{location} must be a ':key' string or a mapping.")
    validate_allowed_keys(value, {"key", "scope", "task"}, location)
    raw_key = value.get("key")
    if not isinstance(raw_key, str) or not raw_key.strip():
        raise PropagateError(f"{location}.key must be a non-empty string.")
    validated_key = validate_context_key(raw_key)
    if not validated_key.startswith(":"):
        raise PropagateError(f"{location}.key must use a reserved ':'-prefixed context key.")
    scope = value.get("scope", "execution")
    if scope not in {"execution", "global", "task"}:
        raise PropagateError(f"{location}.scope must be one of: execution, global, task.")
    task = value.get("task")
    if task is not None and (not isinstance(task, str) or not task.strip()):
        raise PropagateError(f"{location}.task must be a non-empty string when provided.")
    if scope != "task" and task is not None:
        raise PropagateError(f"{location}.task is only allowed when scope is 'task'.")
    return ScopedContextKey(key=validated_key, scope=scope, task=task)


def coerce_scoped_context_key(value: ScopedContextKey | str) -> ScopedContextKey:
    if isinstance(value, ScopedContextKey):
        return value
    return parse_scoped_context_key(value, "Scoped context key")


def parse_context_condition(value: Any, location: str) -> ContextCondition | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise PropagateError(f"{location} must be a non-empty string when provided.")
        negate = False
        if stripped.startswith("!:"):
            negate = True
            stripped = stripped[1:]
        elif not stripped.startswith(":"):
            raise PropagateError(f"{location} must be a ':key' or '!:key' context reference.")
        return ContextCondition(ref=parse_scoped_context_key(stripped, location), negate=negate)
    if not isinstance(value, dict):
        raise PropagateError(f"{location} must be a ':key' string or a mapping.")
    validate_allowed_keys(value, {"key", "scope", "task", "negate"}, location)
    negate = value.get("negate", False)
    if not isinstance(negate, bool):
        raise PropagateError(f"{location}.negate must be a boolean when provided.")
    ref_value = {key: raw for key, raw in value.items() if key != "negate"}
    return ContextCondition(ref=parse_scoped_context_key(ref_value, location), negate=negate)


def coerce_context_condition(value: ContextCondition | str) -> ContextCondition:
    if isinstance(value, ContextCondition):
        return value
    condition = parse_context_condition(value, "Context condition")
    assert condition is not None
    return condition


def resolve_context_ref_dir(
    context_root: Path,
    execution_name: str,
    task_id: str,
    ref: ScopedContextKey,
    *,
    for_write: bool = False,
) -> Path:
    ref = coerce_scoped_context_key(ref)
    resolver = resolve_context_dir_for_write if for_write else resolve_context_dir_for_read
    if ref.scope == "global":
        return resolver(context_root, execution_name, task_id, scope_global=True)
    if ref.scope == "task":
        if ref.task is not None:
            return resolver(context_root, execution_name, task_id, scope_task=ref.task)
        return resolver(context_root, execution_name, task_id, scope_local=True)
    return resolver(context_root, execution_name, task_id)


def read_scoped_context_value(runtime_context: RuntimeContext, ref: ScopedContextKey) -> str:
    ref = coerce_scoped_context_key(ref)
    context_dir = resolve_context_ref_dir(
        runtime_context.context_root,
        runtime_context.execution_name,
        runtime_context.task_id,
        ref,
    )
    return read_context_value(context_dir, ref.key)


def write_scoped_context_value(runtime_context: RuntimeContext, ref: ScopedContextKey, value: str) -> None:
    ref = coerce_scoped_context_key(ref)
    context_dir = resolve_context_ref_dir(
        runtime_context.context_root,
        runtime_context.execution_name,
        runtime_context.task_id,
        ref,
        for_write=True,
    )
    write_context_value(context_dir, ref.key, value)


def evaluate_context_condition(runtime_context: RuntimeContext, condition: ContextCondition) -> bool:
    condition = coerce_context_condition(condition)
    context_dir = resolve_context_ref_dir(
        runtime_context.context_root,
        runtime_context.execution_name,
        runtime_context.task_id,
        condition.ref,
    )
    key_path = context_dir / condition.ref.key
    truthy = key_path.is_file() and key_path.read_text(encoding="utf-8") != ""
    return not truthy if condition.negate else truthy
