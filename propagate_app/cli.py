from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from .config_load import load_config
from .constants import ENV_CONTEXT_ROOT, ENV_EXECUTION, ENV_TASK, LOGGER, configure_logging
from .context_store import (
    context_dump_command,
    context_get_command,
    context_set_command,
    resolve_context_dir_for_read,
    resolve_context_dir_for_write,
)
from .errors import PropagateError
from .models import ExecutionScheduleState, RunState, RuntimeContext
from .run_state import load_run_state, state_file_path
from .scheduler import run_execution_schedule
from .signals import log_active_signal, parse_active_signal, select_initial_execution


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="propagate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run an execution from a config file.")
    run_parser.add_argument("--config", required=True, help="Path to the Propagate YAML config.")
    run_parser.add_argument("--execution", help="Execution name to run.")
    run_parser.add_argument("--signal", help="Signal name to activate for this run.")
    run_parser.add_argument("--signal-payload", help="Signal payload as a YAML or JSON mapping. Requires --signal.")
    run_parser.add_argument("--signal-file", help="Path to a YAML or JSON signal document containing 'type' and optional 'payload'.")
    run_parser.add_argument("--resume", action="store_true", default=False, help="Resume a previously interrupted run.")
    context_parser = subparsers.add_parser("context", help="Manage local context values.")
    context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)
    set_parser = context_subparsers.add_parser("set", help="Store a local context value.")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    _add_write_scope_flags(set_parser)
    get_parser = context_subparsers.add_parser("get", help="Read a local context value.")
    get_parser.add_argument("key")
    _add_read_scope_flags(get_parser)
    context_subparsers.add_parser("dump", help="Dump all context keys as YAML.")
    return parser


def _add_write_scope_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--global", dest="scope_global", action="store_true", default=False, help="Use global context scope.")
    group.add_argument("--local", dest="scope_local", action="store_true", default=False, help="Use task-local context scope.")


def _add_read_scope_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--global", dest="scope_global", action="store_true", default=False, help="Use global context scope.")
    group.add_argument("--local", dest="scope_local", action="store_true", default=False, help="Use task-local context scope.")
    group.add_argument("--task", dest="scope_task", type=str, default=None, help="Read from a specific execution/task context.")


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        command_result = dispatch_command(args, Path.cwd())
        if command_result is not None:
            return command_result
    except PropagateError as error:
        LOGGER.error("%s", error)
        return 1
    parser.error(f"Unsupported command: {args.command}")
    return 2


def dispatch_command(args: argparse.Namespace, working_dir: Path) -> int | None:
    if args.command == "run":
        return run_command(args.config, args.execution, args.signal, args.signal_payload, args.signal_file, args.resume)
    if args.command == "context":
        context_root_env = os.environ.get(ENV_CONTEXT_ROOT, "")
        execution_env = os.environ.get(ENV_EXECUTION, "")
        task_env = os.environ.get(ENV_TASK, "")
        context_root = Path(context_root_env) if context_root_env else (working_dir / ".propagate-context")
        scope_global = getattr(args, "scope_global", False)
        scope_local = getattr(args, "scope_local", False)
        scope_task = getattr(args, "scope_task", None)
        if args.context_command == "set":
            context_dir = resolve_context_dir_for_write(
                context_root,
                execution_env,
                task_env,
                scope_global=scope_global,
                scope_local=scope_local,
            )
            return context_set_command(args.key, args.value, context_dir)
        if args.context_command == "get":
            context_dir = resolve_context_dir_for_read(
                context_root,
                execution_env,
                task_env,
                scope_global=scope_global,
                scope_local=scope_local,
                scope_task=scope_task,
            )
            return context_get_command(args.key, context_dir)
        if args.context_command == "dump":
            return context_dump_command(context_root)
    return None


def run_command(
    config_value: str,
    execution_name: str | None,
    signal_name: str | None,
    signal_payload: str | None,
    signal_file: str | None,
    resume: bool = False,
) -> int:
    config_path = Path(config_value).expanduser()
    if resume:
        if any(v is not None for v in (execution_name, signal_name, signal_payload, signal_file)):
            raise PropagateError("--resume cannot be combined with --execution, --signal, --signal-payload, or --signal-file.")
        return _run_resume(config_path)
    return _run_fresh(config_path, execution_name, signal_name, signal_payload, signal_file)


def _run_resume(config_path: Path) -> int:
    try:
        run_state = load_run_state(config_path)
        config = load_config(config_path, existing_clones=run_state.cloned_repos)
        active_signal = run_state.active_signal
        log_active_signal(active_signal)
        initialized_dirs = set(run_state.initialized_signal_context_dirs)
        run_execution_schedule(
            config,
            run_state.initial_execution,
            RuntimeContext(
                agent_command=config.agent.command,
                context_sources=config.context_sources,
                active_signal=active_signal,
                initialized_signal_context_dirs=initialized_dirs,
            ),
            run_state=run_state,
        )
        return 0
    except PropagateError as error:
        LOGGER.error("%s", error)
        _log_resume_hint(config_path)
        return 1
    except KeyboardInterrupt:
        _log_resume_hint(config_path)
        return 130


def _run_fresh(
    config_path: Path,
    execution_name: str | None,
    signal_name: str | None,
    signal_payload: str | None,
    signal_file: str | None,
) -> int:
    config = load_config(config_path)
    active_signal = parse_active_signal(signal_name, signal_payload, signal_file, config.signals)
    log_active_signal(active_signal)
    initial_execution = select_initial_execution(config, execution_name, active_signal)
    cloned_repos: dict[str, Path] = {}
    for name, repo in config.repositories.items():
        if repo.url is not None and repo.path is not None:
            cloned_repos[name] = repo.path
    run_state = RunState(
        config_path=config.config_path,
        initial_execution=initial_execution.name,
        schedule=ExecutionScheduleState(active_names=set(), completed_names=set()),
        active_signal=active_signal,
        cloned_repos=cloned_repos,
        initialized_signal_context_dirs=set(),
    )
    initialized_dirs: set[Path] = set()
    try:
        run_execution_schedule(
            config,
            initial_execution.name,
            RuntimeContext(
                agent_command=config.agent.command,
                context_sources=config.context_sources,
                active_signal=active_signal,
                initialized_signal_context_dirs=initialized_dirs,
            ),
            run_state=run_state,
        )
        return 0
    except PropagateError as error:
        LOGGER.error("%s", error)
        _log_resume_hint(config_path)
        return 1
    except KeyboardInterrupt:
        _log_resume_hint(config_path)
        return 130


def _log_resume_hint(config_path: Path) -> None:
    if state_file_path(config_path).exists():
        LOGGER.error("Use --resume to continue from where it left off.")
