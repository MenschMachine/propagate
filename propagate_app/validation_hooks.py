from __future__ import annotations

import json
import shlex
from pathlib import Path

from .context_store import read_context_value, resolve_context_dir_for_read
from .errors import PropagateError
from .models import RuntimeContext
from .processes import run_process_command
from .validation import validate_context_key, validate_context_source_name

_KNOWN_VALIDATE_COMMANDS = {"context-key", "github-pr"}


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
    elif validate_command == "context-key":
        _validate_context_key_args(args, f"{location} '{phase}' hook #{hook_index} '{command}'")


def run_validate_hook_command(action: str, runtime_context: RuntimeContext) -> None:
    parts = shlex.split(action)
    command = parts[0][len("validate:"):]
    args = _parse_key_value_args(parts[1:], f"Validation command '{action}'")
    if command == "github-pr":
        _run_validate_github_pr(args, runtime_context)
        return
    if command == "context-key":
        _run_validate_context_key(args, runtime_context)
        return


def _validate_github_pr_args(args: dict[str, str], location: str) -> None:
    allowed = {"repo", "repo_from", "pr_from", "require_merged"}
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise PropagateError(f"{location} has unknown argument '{unknown[0]}'.")
    if ("repo" in args) == ("repo_from" in args):
        raise PropagateError(f"{location} requires exactly one of 'repo=<owner/name>' or 'repo_from=<source>'.")
    if "pr_from" not in args or not args["pr_from"]:
        raise PropagateError(f"{location} requires 'pr_from=<source>'.")
    if "require_merged" in args and args["require_merged"] not in {"true", "false"}:
        raise PropagateError(f"{location} 'require_merged' must be 'true' or 'false'.")
    if "repo_from" in args:
        _validate_value_source(args["repo_from"], location, allow_signal=True)
    _validate_value_source(args["pr_from"], location, allow_signal=True)


def _validate_context_key_args(args: dict[str, str], location: str) -> None:
    allowed = {"key", "scope", "equals"}
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise PropagateError(f"{location} has unknown argument '{unknown[0]}'.")
    if "key" not in args or not args["key"]:
        raise PropagateError(f"{location} requires 'key=:context-key'.")
    validate_context_key(args["key"])
    if "scope" in args:
        _validate_context_scope(args["scope"], location)


def _validate_value_source(source: str, location: str, *, allow_signal: bool) -> None:
    if allow_signal and source.startswith("signal."):
        field_name = source[len("signal."):]
        if not field_name:
            raise PropagateError(f"{location} signal source must be 'signal.<field>'.")
        return
    if not source.startswith("context:"):
        allowed = "'signal.<field>' or 'context:<scope>/:key'" if allow_signal else "'context:<scope>/:key'"
        raise PropagateError(f"{location} source must be {allowed}.")
    scope_and_key = source[len("context:"):]
    try:
        scope, key = scope_and_key.rsplit("/", 1)
    except ValueError as error:
        raise PropagateError(
            f"{location} source must be 'context:<scope>/:key'."
        ) from error
    if not scope:
        raise PropagateError(f"{location} source must include a scope.")
    _validate_context_scope(scope, location)
    validate_context_key(key)


def _validate_context_scope(scope: str, location: str) -> None:
    if scope == "global":
        return
    parts = scope.split("/")
    if len(parts) > 2 or any(not part for part in parts):
        raise PropagateError(f"{location} scope must be 'global', 'execution', or 'execution/task'.")
    for part in parts:
        validate_context_source_name(part)


def _run_validate_github_pr(args: dict[str, str], runtime_context: RuntimeContext) -> None:
    repo = args["repo"] if "repo" in args else _resolve_value_source(args["repo_from"], runtime_context)
    pr_number = _resolve_value_source(args["pr_from"], runtime_context)
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


def _run_validate_context_key(args: dict[str, str], runtime_context: RuntimeContext) -> None:
    key = validate_context_key(args["key"])
    context_dir = _resolve_context_scope(args.get("scope"), runtime_context)
    value = read_context_value(context_dir, key).strip()
    if not value:
        raise PropagateError(f"Context key '{key}' is empty in {context_dir}.")
    expected = args.get("equals")
    if expected is not None and value != expected:
        raise PropagateError(f"Context key '{key}' in {context_dir} expected '{expected}' but was '{value}'.")


def _resolve_value_source(source: str, runtime_context: RuntimeContext) -> str:
    if source.startswith("signal."):
        field_name = source[len("signal."):]
        active_signal = runtime_context.active_signal
        if active_signal is None:
            raise PropagateError(f"Validation source '{source}' requires an active signal.")
        value = active_signal.payload.get(field_name)
        if value is None:
            raise PropagateError(f"Validation source '{source}' was not found in the active signal.")
        return str(value)
    scope_and_key = source[len("context:"):]
    scope, key = scope_and_key.rsplit("/", 1)
    context_dir = _resolve_context_scope(scope, runtime_context)
    return read_context_value(context_dir, validate_context_key(key)).strip()


def _resolve_context_scope(scope: str | None, runtime_context: RuntimeContext) -> Path:
    if scope == "global":
        return resolve_context_dir_for_read(
            runtime_context.context_root,
            runtime_context.execution_name,
            runtime_context.task_id,
            scope_global=True,
        )
    if scope is None:
        return resolve_context_dir_for_read(
            runtime_context.context_root,
            runtime_context.execution_name,
            runtime_context.task_id,
        )
    _validate_context_scope(scope, "Validation command")
    return resolve_context_dir_for_read(
        runtime_context.context_root,
        runtime_context.execution_name,
        runtime_context.task_id,
        scope_task=scope,
    )


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
