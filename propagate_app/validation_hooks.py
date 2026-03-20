from __future__ import annotations

import json
import shlex

from .context_store import read_context_value, resolve_context_dir_for_read
from .errors import PropagateError
from .models import RuntimeContext
from .processes import run_process_command
from .validation import validate_context_key

_KNOWN_VALIDATE_COMMANDS = {"github-pr"}


def validate_hook_action(action: str, location: str, phase: str, hook_index: int) -> None:
    parts = shlex.split(action)
    if not parts:
        raise PropagateError(f"{location} '{phase}' hook #{hook_index} must be a non-empty string.")
    command = parts[0]
    if not command.startswith("validate:"):
        raise PropagateError(f"{location} '{phase}' hook #{hook_index} uses unknown validation command '{action}'.")
    validate_command = command[len("validate:"):]
    if validate_command not in _KNOWN_VALIDATE_COMMANDS:
        raise PropagateError(
            f"{location} '{phase}' hook #{hook_index} uses unknown validation command '{action}'."
            f" Known commands: {', '.join(sorted(_KNOWN_VALIDATE_COMMANDS))}."
        )
    args = _parse_key_value_args(parts[1:], f"{location} '{phase}' hook #{hook_index} '{command}'")
    if validate_command == "github-pr":
        _validate_github_pr_args(args, f"{location} '{phase}' hook #{hook_index} '{command}'")


def run_validate_hook_command(action: str, runtime_context: RuntimeContext) -> None:
    parts = shlex.split(action)
    command = parts[0][len("validate:"):]
    args = _parse_key_value_args(parts[1:], f"Validation command '{action}'")
    if command == "github-pr":
        _run_validate_github_pr(args, runtime_context)
        return


def _validate_github_pr_args(args: dict[str, str], location: str) -> None:
    allowed = {"repo", "pr_from", "require_merged"}
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise PropagateError(f"{location} has unknown argument '{unknown[0]}'.")
    if "repo" not in args or not args["repo"]:
        raise PropagateError(f"{location} requires 'repo=<owner/name>'.")
    if "pr_from" not in args or not args["pr_from"]:
        raise PropagateError(f"{location} requires 'pr_from=<source>'.")
    if "require_merged" in args and args["require_merged"] not in {"true", "false"}:
        raise PropagateError(f"{location} 'require_merged' must be 'true' or 'false'.")
    _validate_pr_source(args["pr_from"], location)


def _validate_pr_source(source: str, location: str) -> None:
    if source == "signal.pr_number":
        return
    if not source.startswith("context:"):
        raise PropagateError(
            f"{location} 'pr_from' must be 'signal.pr_number' or 'context:<execution>/:key'."
        )
    scope_and_key = source[len("context:"):]
    try:
        scope, key = scope_and_key.rsplit("/", 1)
    except ValueError as error:
        raise PropagateError(
            f"{location} 'pr_from' must be 'context:<execution>/:key'."
        ) from error
    if not scope:
        raise PropagateError(f"{location} 'pr_from' must include an execution scope.")
    validate_context_key(key)


def _run_validate_github_pr(args: dict[str, str], runtime_context: RuntimeContext) -> None:
    repo = args["repo"]
    pr_number = _resolve_pr_number(args["pr_from"], runtime_context)
    require_merged = args.get("require_merged", "false") == "true"
    result = run_process_command(
        ["gh", "pr", "view", pr_number, "--repo", repo, "--json", "number,state,mergedAt"],
        runtime_context.working_dir,
        failure_message=f"validate:github-pr failed for repo '{repo}' and PR #{pr_number} with exit code {{exit_code}}.",
        start_failure_message="Failed to start validate:github-pr: {error}",
        capture_output=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise PropagateError(f"validate:github-pr returned invalid JSON for repo '{repo}' and PR #{pr_number}.") from error
    if require_merged and not payload.get("mergedAt"):
        raise PropagateError(f"PR #{pr_number} in '{repo}' is not merged.")


def _resolve_pr_number(source: str, runtime_context: RuntimeContext) -> str:
    if source == "signal.pr_number":
        active_signal = runtime_context.active_signal
        if active_signal is None:
            raise PropagateError("validate:github-pr requires an active signal for 'signal.pr_number'.")
        pr_number = active_signal.payload.get("pr_number")
        if pr_number is None:
            raise PropagateError("validate:github-pr could not find 'pr_number' in the active signal.")
        return str(pr_number)
    scope_and_key = source[len("context:"):]
    scope, key = scope_and_key.rsplit("/", 1)
    context_dir = resolve_context_dir_for_read(
        runtime_context.context_root,
        runtime_context.execution_name,
        runtime_context.task_id,
        scope_task=scope,
    )
    return read_context_value(context_dir, validate_context_key(key)).strip()


def _parse_key_value_args(parts: list[str], location: str) -> dict[str, str]:
    args: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            raise PropagateError(f"{location} argument '{part}' must be in key=value form.")
        key, value = part.split("=", 1)
        if not key or not value:
            raise PropagateError(f"{location} argument '{part}' must be in key=value form.")
        args[key] = value
    return args
