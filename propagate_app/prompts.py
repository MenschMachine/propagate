from pathlib import Path

from .constants import LOGGER
from .context_refs import coerce_scoped_context_key
from .context_store import append_context_to_prompt, load_merged_context
from .errors import PropagateError
from .models import RuntimeContext, ScopedContextKey


def build_sub_task_prompt(
    prompt_path: Path,
    task_id: str,
    runtime_context: RuntimeContext,
    must_set: list[ScopedContextKey | str] | None = None,
) -> str:
    prompt_text = read_prompt(prompt_path)
    LOGGER.info(
        "Loading merged context for sub-task '%s' (global + execution '%s' + task '%s').",
        task_id,
        runtime_context.execution_name,
        runtime_context.task_id or "(none)",
    )
    items = load_merged_context(runtime_context.context_root, runtime_context.execution_name, runtime_context.task_id)
    result = append_context_to_prompt(prompt_text, items)
    if must_set:
        result = append_must_set_notice(result, must_set)
    return result


def _format_context_set_command(ref: ScopedContextKey | str) -> tuple[str, str]:
    scoped_ref = coerce_scoped_context_key(ref)
    if scoped_ref.scope == "global":
        return scoped_ref.key, f'propagate context set --global {scoped_ref.key} "<value>"'
    if scoped_ref.scope == "task":
        task = scoped_ref.task or "<execution>/<task>"
        return scoped_ref.key, f'propagate context set --task {task} {scoped_ref.key} "<value>"'
    return scoped_ref.key, f'propagate context set {scoped_ref.key} "<value>"'


def append_must_set_notice(prompt_text: str, must_set: list[ScopedContextKey | str]) -> str:
    lines = [
        "## Required Context Keys",
        "",
        "You MUST set the following context keys before completing this task:",
    ]
    commands: list[str] = []
    for ref in must_set:
        key, command = _format_context_set_command(ref)
        lines.append(f"- `{key}`")
        commands.append(command)
    lines.append("")
    lines.append("Use these commands to set them:")
    for command in commands:
        lines.append(f"- `{command}`")
    section = "\n".join(lines) + "\n"
    if prompt_text.endswith("\n\n"):
        return prompt_text + section
    if prompt_text.endswith("\n"):
        return prompt_text + "\n" + section
    return prompt_text + "\n\n" + section


def read_prompt(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise PropagateError(f"Prompt file does not exist: {prompt_path}")
    if not prompt_path.is_file():
        raise PropagateError(f"Prompt path is not a file: {prompt_path}")
    try:
        return prompt_path.read_text(encoding="utf-8")
    except OSError as error:
        raise PropagateError(f"Failed to read prompt file {prompt_path}: {error}") from error
