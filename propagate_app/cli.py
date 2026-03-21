from __future__ import annotations

import argparse
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from .config_load import load_config
from .constants import ENV_CONTEXT_ROOT, ENV_EXECUTION, ENV_TASK, LOGGER, configure_logging
from .context_store import (
    clear_all_context,
    context_delete_command,
    context_dump_command,
    context_get_command,
    context_set_command,
    get_context_root,
    resolve_context_dir_for_read,
    resolve_context_dir_for_write,
)
from .errors import PropagateError, build_named_error
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
    run_parser.add_argument("--stop-after", default=None, help="Stop the run after the named execution completes.")
    send_signal_parser = subparsers.add_parser("send-signal", help="Send a signal to a running propagate instance.")
    send_signal_parser.add_argument("--project", required=True, help="Project name to send the signal to.")
    send_signal_source = send_signal_parser.add_mutually_exclusive_group(required=True)
    send_signal_source.add_argument("--signal", help="Signal type name.")
    send_signal_source.add_argument("--signal-file", help="Path to a YAML or JSON signal document containing 'type' and optional 'payload'.")
    send_signal_parser.add_argument("--signal-payload", help="Signal payload as a YAML or JSON mapping. Requires --signal.")
    context_parser = subparsers.add_parser("context", help="Manage local context values.")
    context_parser.add_argument("--config", dest="context_config", default=None, help="Path to config file (used to derive context root when PROPAGATE_CONTEXT_ROOT is not set).")
    context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)
    set_parser = context_subparsers.add_parser("set", help="Store a local context value.")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    _add_write_scope_flags(set_parser)
    delete_parser = context_subparsers.add_parser("delete", help="Delete a local context value.")
    delete_parser.add_argument("key")
    _add_write_scope_flags(delete_parser)
    get_parser = context_subparsers.add_parser("get", help="Read a local context value.")
    get_parser.add_argument("key")
    _add_read_scope_flags(get_parser)
    context_subparsers.add_parser("dump", help="Dump all context keys as YAML.")
    serve_parser = subparsers.add_parser("serve", help="Run as a long-lived server, listening for signals.")
    serve_parser.add_argument("--config", action="append", default=[], help="Path to a Propagate YAML config (repeatable).")
    serve_parser.add_argument("--resume", nargs="?", const=True, default=False, help="Resume a previously interrupted run, optionally from a specific execution/task.")
    serve_parser.add_argument(
        "--worker-stdout-log",
        help="Write worker stdout transcripts to this file instead of mirroring them to stdout.",
    )
    worker_parser = subparsers.add_parser("serve-worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("--config", required=True)
    worker_parser.add_argument("--resume", nargs="?", const=True, default=False)
    clear_parser = subparsers.add_parser("clear", help="Clear all context and run state.")
    clear_parser.add_argument("--config", required=True, help="Path to the Propagate YAML config.")
    clear_parser.add_argument("-f", "--force", action="store_true", default=False, help="Also delete cloned repositories.")
    subparsers.add_parser("shell", help="Interactive REPL for a running propagate instance.")
    validate_parser = subparsers.add_parser("validate", help="Validate a config file without running.")
    validate_parser.add_argument("--config", required=True, help="Path to the Propagate YAML config.")
    fail_parser = subparsers.add_parser("fail", help="Abort the current run with a structured failure kind.")
    fail_parser.add_argument("kind", help="Failure kind, for example 'unable-to-implement'.")
    fail_parser.add_argument("message", help="Human-readable failure detail.")
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
        return run_command(args.config, args.execution, args.signal, args.signal_payload, args.signal_file, args.resume, args.stop_after)
    if args.command == "send-signal":
        return send_signal_command(args.project, args.signal, args.signal_payload, args.signal_file)
    if args.command == "serve":
        return serve_command(args.config, resume=args.resume, worker_stdout_log=args.worker_stdout_log)
    if args.command == "serve-worker":
        from .serve import serve_worker_command
        return serve_worker_command(args.config, resume=args.resume)
    if args.command == "clear":
        return clear_command(args.config, force=args.force)
    if args.command == "shell":
        from .shell import shell_command
        return shell_command()
    if args.command == "validate":
        return validate_command(args.config)
    if args.command == "fail":
        return fail_command(args.kind, args.message)
    if args.command == "context":
        context_root_env = os.environ.get(ENV_CONTEXT_ROOT, "")
        execution_env = os.environ.get(ENV_EXECUTION, "")
        task_env = os.environ.get(ENV_TASK, "")
        if context_root_env:
            context_root = Path(context_root_env)
        elif args.context_config:
            context_root = get_context_root(Path(args.context_config).expanduser())
        else:
            context_root = get_context_root(working_dir / "propagate.yaml")
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
        if args.context_command == "delete":
            context_dir = resolve_context_dir_for_write(
                context_root,
                execution_env,
                task_env,
                scope_global=scope_global,
                scope_local=scope_local,
            )
            return context_delete_command(args.key, context_dir)
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
    stop_after: str | None = None,
) -> int:
    config_path = Path(config_value).expanduser()
    config = load_config(config_path)
    if stop_after is not None:
        _validate_stop_after(stop_after, config)
    if resume:
        if any(v is not None for v in (execution_name, signal_name, signal_payload, signal_file)):
            raise PropagateError("--resume cannot be combined with --execution, --signal, --signal-payload, or --signal-file.")
        if isinstance(resume, str):
            return _run_resume(config, resume_target=resume, stop_after=stop_after)
        return _run_resume(config, stop_after=stop_after)
    return _run_fresh(config, execution_name, signal_name, signal_payload, signal_file, stop_after=stop_after)


def _run_resume(config: Config, resume_target: str | None = None, stop_after: str | None = None) -> int:
    config_path = config.config_path
    signal_socket = None
    address = None
    try:
        run_state = apply_forced_resume_if_targeted(config_path, config, resume_target)
        active_signal = run_state.active_signal
        log_active_signal(active_signal)
        initialized_dirs = set(run_state.initialized_signal_context_dirs)
        address = socket_address(config.config_path)
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
                signal_configs=config.signals,
                config_dir=config.config_path.parent,
            ),
            run_state=run_state,
            signal_socket=signal_socket,
            stop_after=stop_after,
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
    config: Config,
    execution_name: str | None,
    signal_name: str | None,
    signal_payload: str | None,
    signal_file: str | None,
    stop_after: str | None = None,
) -> int:
    config_path = config.config_path
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
                signal_configs=config.signals,
                config_dir=config.config_path.parent,
            ),
            run_state=run_state,
            signal_socket=signal_socket,
            stop_after=stop_after,
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
    project: str,
    signal_name: str | None,
    signal_payload: str | None,
    signal_file: str | None,
) -> int:
    from .signal_transport import COORDINATOR_ADDRESS
    from .signals import load_signal_file, parse_signal_payload_mapping

    if signal_file is not None:
        signal_type, payload = load_signal_file(Path(signal_file).expanduser().resolve())
    elif signal_name is not None:
        signal_type = signal_name
        payload = parse_signal_payload_mapping(
            signal_payload if signal_payload is not None else "{}",
            f"Signal '{signal_name}' payload",
        )
    else:
        raise PropagateError("Signal type is required for send-signal.")

    push = connect_push_socket(COORDINATOR_ADDRESS)
    try:
        send_signal(push, signal_type, payload, metadata={"project": project})
        LOGGER.info("Sent signal '%s' to project '%s'.", signal_type, project)
    finally:
        close_push_socket(push)
    return 0


def clear_command(config_value: str, force: bool = False) -> int:
    config_path = Path(config_value).expanduser().resolve()
    if not config_path.exists():
        raise PropagateError(f"Config file not found: {config_path}")
    cleared = []
    context_roots: list[Path] = []
    default_context_root = get_context_root(config_path)
    context_roots.append(default_context_root)
    context_root_env = os.environ.get(ENV_CONTEXT_ROOT, "")
    if context_root_env:
        env_context_root = Path(context_root_env).expanduser().resolve()
        if env_context_root not in context_roots:
            context_roots.append(env_context_root)
    for context_root in context_roots:
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


def validate_command(config_value: str) -> int:
    config_path = Path(config_value).expanduser()
    load_config(config_path)
    LOGGER.info("Config is valid: %s", config_path)
    return 0


def fail_command(kind: str, message: str) -> NoReturn:
    raise build_named_error(kind, message)


def _validate_stop_after(stop_after: str, config: Config) -> None:
    if stop_after not in config.executions:
        raise PropagateError(f"--stop-after execution '{stop_after}' not found in config.")
def _log_resume_hint(config_path: Path) -> None:
    if state_file_path(config_path).exists():
        LOGGER.error("Use --resume to continue from where it left off.")
