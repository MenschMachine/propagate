from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from .errors import PropagateError
from .constants import LOGGER
from .validation import validate_context_key


def get_context_dir(working_dir: Path) -> Path:
    return working_dir / ".propagate-context"


def context_set_command(key: str, value: str, working_dir: Path) -> int:
    validated_key = validate_context_key(key)
    context_dir = get_context_dir(working_dir)
    ensure_context_dir(context_dir)
    write_context_value(context_dir, validated_key, value)
    LOGGER.info("Stored context key '%s'.", validated_key)
    return 0


def context_get_command(key: str, working_dir: Path) -> int:
    sys.stdout.write(read_context_value(get_context_dir(working_dir), validate_context_key(key)))
    return 0


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
        entries = sorted(context_dir.iterdir(), key=lambda entry: entry.name)
    except OSError as error:
        raise PropagateError(f"Failed to read context directory {context_dir}: {error}") from error
    return [
        (validate_context_key(entry.name), read_context_entry(context_dir, entry.name, entry))
        for entry in entries
    ]


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
