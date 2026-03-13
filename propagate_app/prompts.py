from pathlib import Path

from .constants import LOGGER
from .context_store import append_context_to_prompt, load_merged_context
from .errors import PropagateError
from .models import RuntimeContext


def build_sub_task_prompt(prompt_path: Path, task_id: str, runtime_context: RuntimeContext) -> str:
    prompt_text = read_prompt(prompt_path)
    LOGGER.info(
        "Loading merged context for sub-task '%s' (global + execution '%s' + task '%s').",
        task_id,
        runtime_context.execution_name,
        runtime_context.task_id or "(none)",
    )
    items = load_merged_context(runtime_context.context_root, runtime_context.execution_name, runtime_context.task_id)
    return append_context_to_prompt(prompt_text, items)


def read_prompt(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise PropagateError(f"Prompt file does not exist: {prompt_path}")
    if not prompt_path.is_file():
        raise PropagateError(f"Prompt path is not a file: {prompt_path}")
    try:
        return prompt_path.read_text(encoding="utf-8")
    except OSError as error:
        raise PropagateError(f"Failed to read prompt file {prompt_path}: {error}") from error
