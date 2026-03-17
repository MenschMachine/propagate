from __future__ import annotations

import argparse
import os
import shutil
from collections.abc import Sequence
from pathlib import Path

from .config_load import load_config
from .constants import ENV_CONTEXT_ROOT, ENV_EXECUTION, ENV_TASK, LOGGER, configure_logging
from .context_store import (
    clear_all_context,
    context_dump_command,
    context_get_command,
    context_set_command,
    get_context_root,
    resolve_context_dir_for_read,
    resolve_context_dir_for_write,
)
from .errors import PropagateError
from .models import Config, ExecutionScheduleState, RunState, RuntimeContext
from .repo_clone import is_propagate_clone
from .run_state import (
    apply_forced_resume_if_targeted,
    clear_run_state,
    read_cloned_repos,
    state_file_path,
)
from .scheduler import run_execution_schedule
from .serve import serve_command
from .signal_transport import bind_pull_socket, close_pull_socket, close_push_socket, connect_push_socket, send_signal, socket_address
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
    run_parser.add_argument("--resume", nargs="?", const=True, default=False, help="Resume a previously interrupted run, optionally from a specific execution/task.")
    send_signal_parser = subparsers.add_parser("send-signal", help="Send a signal to a running propagate instance.")
    send_signal_parser.add_argument("--config", required=True, help="Config path (used to determine socket address).")
    send_signal_source = send_signal_parser.add_mutually_exclusive_group(required=True)
    send_signal_source.add_argument("--signal", help="Signal type name.")
    send_signal_source.add_argument("--signal-file", help="Path to a YAML or JSON signal document containing 'type' and optional 'payload'.")
    send_signal_parser.add_argument("--signal-payload", help="Signal payload as a YAML or JSON mapping. Requires --signal.")
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
    serve_parser = subparsers.add_parser("serve", help="Run as a long-lived server, listening for signals.")
    serve_parser.add_argument("--config", required=True, help="Path to the Propagate YAML config.")
    serve_parser.add_argument("--resume", nargs="?", const=True, default=False, help="Resume a previously interrupted run, optionally from a specific execution/task.")
    clear_parser = subparsers.add_parser("clear", help="Clear all context and run state.")
    clear_parser.add_argument("--config", required=True, help="Path to the Propagate YAML config.")
    clear_parser.add_argument("-f", "--force", action="store_true", default=False, help="Also delete cloned repositories.")
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
    from dotenv import load_dotenv
    load_dotenv()
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
    if args.command == "send-signal":
        return send_signal_command(args.config, args.signal, args.signal_payload, args.signal_file)
    if args.command == "serve":
        return serve_command(args.config, resume=args.resume)
    if args.command == "clear":
        return clear_command(args.config, force=args.force)
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
    resume: bool | str = False,
) -> int:
    config_path = Path(config_value).expanduser()
    if resume:
        if any(v is not None for v in (execution_name, signal_name, signal_payload, signal_file)):
            raise PropagateError("--resume cannot be combined with --execution, --signal, --signal-payload, or --signal-file.")
        if isinstance(resume, str):
            return _run_resume(config_path, resume_target=resume)
        return _run_resume(config_path)
    return _run_fresh(config_path, execution_name, signal_name, signal_payload, signal_file)


def _run_resume(config_path: Path, resume_target: str | None = None) -> int:
    signal_socket = None
    address = None
    try:
        config = load_config(config_path)
        run_state = apply_forced_resume_if_targeted(config_path, config, resume_target)
        active_signal = run_state.active_signal
        log_active_signal(active_signal)
        initialized_dirs = set(run_state.initialized_signal_context_dirs)
        address = socket_address(config.config_path)
        if _has_signal_gated_triggers(config):
            signal_socket = bind_pull_socket(address)
            LOGGER.info("Listening for external signals on %s", address)
        run_execution_schedule(
            config,
            run_state.initial_execution,
            RuntimeContext(
                agent_command=config.agent.command,
                context_sources=config.context_sources,
                active_signal=active_signal,
                initialized_signal_context_dirs=initialized_dirs,
                config_dir=config.config_path.parent,
            ),
            run_state=run_state,
            signal_socket=signal_socket,
        )
        return 0
    except PropagateError as error:
        LOGGER.error("%s", error)
        _log_resume_hint(config_path)
        return 1
    except KeyboardInterrupt:
        _log_resume_hint(config_path)
        return 130
    finally:
        if signal_socket is not None:
            close_pull_socket(signal_socket, address)


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
    run_state = RunState(
        config_path=config.config_path,
        initial_execution=initial_execution.name,
        schedule=ExecutionScheduleState(active_names=set(), completed_names=set()),
        active_signal=active_signal,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
    )
    initialized_dirs: set[Path] = set()
    signal_socket = None
    address = socket_address(config.config_path)
    try:
        if _has_signal_gated_triggers(config):
            signal_socket = bind_pull_socket(address)
            LOGGER.info("Listening for external signals on %s", address)
        run_execution_schedule(
            config,
            initial_execution.name,
            RuntimeContext(
                agent_command=config.agent.command,
                context_sources=config.context_sources,
                active_signal=active_signal,
                initialized_signal_context_dirs=initialized_dirs,
                config_dir=config.config_path.parent,
            ),
            run_state=run_state,
            signal_socket=signal_socket,
        )
        return 0
    except PropagateError as error:
        LOGGER.error("%s", error)
        _log_resume_hint(config_path)
        return 1
    except KeyboardInterrupt:
        _log_resume_hint(config_path)
        return 130
    finally:
        if signal_socket is not None:
            close_pull_socket(signal_socket, address)


def send_signal_command(
    config_value: str,
    signal_name: str,
    signal_payload: str | None,
    signal_file: str | None,
) -> int:
    config_path = Path(config_value).expanduser()
    config = load_config(config_path)
    active_signal = parse_active_signal(signal_name, signal_payload, signal_file, config.signals)
    if active_signal is None:
        raise PropagateError("Signal type is required for send-signal.")
    address = socket_address(config.config_path)
    push = connect_push_socket(address)
    try:
        send_signal(push, active_signal.signal_type, active_signal.payload)
        LOGGER.info("Sent signal '%s' to %s", active_signal.signal_type, address)
    finally:
        close_push_socket(push)
    return 0


def clear_command(config_value: str, force: bool = False) -> int:
    config_path = Path(config_value).expanduser().resolve()
    if not config_path.exists():
        raise PropagateError(f"Config file not found: {config_path}")
    context_root_env = os.environ.get(ENV_CONTEXT_ROOT, "")
    context_root = Path(context_root_env) if context_root_env else get_context_root(config_path)
    cleared = []
    if clear_all_context(context_root):
        cleared.append(f"context ({context_root})")
    state_path = state_file_path(config_path)
    cloned_repos: dict[str, Path] = {}
    if force:
        cloned_repos = read_cloned_repos(config_path)
    if force:
        for name, clone_path in cloned_repos.items():
            if not is_propagate_clone(clone_path):
                LOGGER.warning("Skipping non-propagate directory '%s' for repo '%s'.", clone_path, name)
                continue
            try:
                shutil.rmtree(clone_path)
            except OSError as exc:
                LOGGER.warning("Failed to delete clone '%s' at '%s': %s", name, clone_path, exc)
                continue
            LOGGER.debug("Deleted cloned repo '%s' at '%s'.", name, clone_path)
            cleared.append(f"clone {name} ({clone_path})")
    if state_path.exists():
        clear_run_state(config_path)
        cleared.append(f"run state ({state_path})")
    if cleared:
        LOGGER.info("Cleared: %s", ", ".join(cleared))
    else:
        LOGGER.info("Nothing to clear.")
    return 0


def _has_signal_gated_triggers(config: Config) -> bool:
    return any(trigger.on_signal is not None for trigger in config.propagation_triggers)


def _log_resume_hint(config_path: Path) -> None:
    if state_file_path(config_path).exists():
        LOGGER.error("Use --resume to continue from where it left off.")
