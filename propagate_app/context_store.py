from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import PropagateError
from .constants import LOGGER
from .validation import validate_context_key

if TYPE_CHECKING:
    from .models import RuntimeContext


def get_context_root(config_path: Path) -> Path:
    return config_path.parent / ".propagate-context"


def get_global_context_dir(context_root: Path) -> Path:
    return context_root


def get_execution_context_dir(context_root: Path, execution_name: str) -> Path:
    return context_root / execution_name


def get_task_context_dir(context_root: Path, execution_name: str, task_id: str) -> Path:
    return context_root / execution_name / task_id


def resolve_execution_context_dir(runtime_context: RuntimeContext) -> Path:
    return get_execution_context_dir(runtime_context.context_root, runtime_context.execution_name)


def resolve_context_dir_for_write(
    context_root: Path,
    execution_name: str,
    task_id: str,
    *,
    scope_global: bool = False,
    scope_local: bool = False,
) -> Path:
    if scope_global:
        return get_global_context_dir(context_root)
    if scope_local:
        if not task_id:
            raise PropagateError("--local requires a task context (PROPAGATE_TASK must be set).")
        return get_task_context_dir(context_root, execution_name, task_id)
    return get_execution_context_dir(context_root, execution_name)


def resolve_context_dir_for_read(
    context_root: Path,
    execution_name: str,
    task_id: str,
    *,
    scope_global: bool = False,
    scope_local: bool = False,
    scope_task: str | None = None,
) -> Path:
    if scope_global:
        return get_global_context_dir(context_root)
    if scope_local:
        if not task_id:
            raise PropagateError("--local requires a task context (PROPAGATE_TASK must be set).")
        return get_task_context_dir(context_root, execution_name, task_id)
    if scope_task is not None:
        _validate_task_path(scope_task)
        parts = scope_task.split("/", 1)
        if len(parts) == 2:
            return get_task_context_dir(context_root, parts[0], parts[1])
        return get_execution_context_dir(context_root, parts[0])
    return get_execution_context_dir(context_root, execution_name)


def _validate_task_path(task_path: str) -> None:
    if "/" in task_path:
        parts = task_path.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise PropagateError(f"--task value must be 'execution' or 'execution/task', got: '{task_path}'")


def clear_execution_context(context_root: Path, execution_name: str) -> None:
    execution_dir = get_execution_context_dir(context_root, execution_name)
    if not execution_dir.exists():
        return
    LOGGER.debug("Clearing execution context directory: %s", execution_dir)
    shutil.rmtree(execution_dir)
    execution_dir.mkdir(parents=True, exist_ok=True)


def context_set_command(key: str, value: str, context_dir: Path) -> int:
    validated_key = validate_context_key(key)
    ensure_context_dir(context_dir)
    write_context_value(context_dir, validated_key, value)
    LOGGER.info("Stored context key '%s'.", validated_key)
    return 0


def context_get_command(key: str, context_dir: Path) -> int:
    sys.stdout.write(read_context_value(context_dir, validate_context_key(key)))
    return 0


def context_dump_command(context_root: Path) -> int:
    import yaml

    result = load_full_context_tree(context_root)
    sys.stdout.write(yaml.dump(result, default_flow_style=False, sort_keys=True, allow_unicode=True))
    return 0


def load_full_context_tree(context_root: Path) -> dict:
    if not context_root.exists():
        return {}
    tree: dict = {}
    global_items = load_local_context(context_root)
    tree["global"] = dict(global_items)
    executions: dict = {}
    try:
        entries = sorted(context_root.iterdir())
    except OSError as error:
        raise PropagateError(f"Failed to read context root {context_root}: {error}") from error
    for entry in entries:
        if not entry.is_dir():
            continue
        exec_node: dict = {}
        exec_node["context"] = dict(load_local_context(entry))
        tasks: dict = {}
        try:
            sub_entries = sorted(entry.iterdir())
        except OSError as error:
            raise PropagateError(f"Failed to read context directory {entry}: {error}") from error
        for sub_entry in sub_entries:
            if not sub_entry.is_dir():
                continue
            task_items = load_local_context(sub_entry)
            if task_items:
                tasks[sub_entry.name] = dict(task_items)
        exec_node["tasks"] = tasks
        executions[entry.name] = exec_node
    tree["executions"] = executions
    return tree


def ensure_context_dir(context_dir: Path) -> None:
    try:
        context_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PropagateError(f"Failed to create context directory {context_dir}: {error}") from error
    if not context_dir.is_dir():
        raise PropagateError(f"Context path is not a directory: {context_dir}")


def write_context_value(context_dir: Path, key: str, value: str) -> None:
    temp_path: Path | None = None
    target_path = context_dir / key
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{key}.",
            suffix=".tmp",
            dir=context_dir,
            delete=False,
        ) as handle:
            handle.write(value)
            temp_path = Path(handle.name)
        temp_path.replace(target_path)
    except OSError as error:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise PropagateError(f"Failed to write context key '{key}' in {context_dir}: {error}") from error


def read_context_value(context_dir: Path, key: str) -> str:
    require_context_dir(context_dir)
    context_path = context_dir / key
    if not context_path.exists():
        raise PropagateError(f"Context key '{key}' was not found in {context_dir}.")
    return read_context_entry(context_dir, key, context_path)


def load_local_context(context_dir: Path) -> list[tuple[str, str]]:
    if not context_dir.exists():
        return []
    require_context_dir(context_dir)
    try:
        entries = sorted(
            (e for e in context_dir.iterdir() if e.is_file()),
            key=lambda entry: entry.name,
        )
    except OSError as error:
        raise PropagateError(f"Failed to read context directory {context_dir}: {error}") from error
    return [
        (validate_context_key(entry.name), read_context_entry(context_dir, entry.name, entry))
        for entry in entries
    ]


def load_merged_context(context_root: Path, execution_name: str, task_id: str) -> list[tuple[str, str]]:
    global_items = load_local_context(get_global_context_dir(context_root))
    execution_items = load_local_context(get_execution_context_dir(context_root, execution_name))
    if task_id:
        task_items = load_local_context(get_task_context_dir(context_root, execution_name, task_id))
    else:
        task_items = []
    return merge_context_layers(global_items, execution_items, task_items)


def merge_context_layers(*layers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    merged: dict[str, str] = {}
    for layer in layers:
        for key, value in layer:
            merged[key] = value
    return sorted(merged.items())


def require_context_dir(context_dir: Path) -> None:
    if not context_dir.exists():
        raise PropagateError(f"Context directory does not exist: {context_dir}")
    if not context_dir.is_dir():
        raise PropagateError(f"Context path is not a directory: {context_dir}")


def read_context_entry(context_dir: Path, key: str, entry_path: Path) -> str:
    if not entry_path.is_file():
        raise PropagateError(f"Context entry '{key}' is not a file in {context_dir}.")
    try:
        return entry_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise PropagateError(f"Failed to decode context key '{key}' in {context_dir} as UTF-8: {error}") from error
    except OSError as error:
        raise PropagateError(f"Failed to read context key '{key}' in {context_dir}: {error}") from error


def render_context_section(items: list[tuple[str, str]]) -> str:
    blocks = []
    for key, value in items:
        rendered_value = value if value.endswith("\n") else f"{value}\n"
        blocks.append(f"### {key}\n{rendered_value}")
    return "## Context\n\n" + "\n".join(blocks).rstrip("\n") + "\n"


def append_context_to_prompt(prompt_text: str, items: list[tuple[str, str]]) -> str:
    if not items:
        return prompt_text
    context_section = render_context_section(items)
    if not prompt_text:
        return context_section
    if prompt_text.endswith("\n\n"):
        return f"{prompt_text}{context_section}"
    if prompt_text.endswith("\n"):
        return f"{prompt_text}\n{context_section}"
    return f"{prompt_text}\n\n{context_section}"
