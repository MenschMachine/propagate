from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from .config_load import load_config
from .constants import LOGGER
from .context_store import context_get_command, context_set_command
from .errors import PropagateError
from .models import RuntimeContext
from .scheduler import run_execution_schedule
from .signals import log_active_signal, parse_active_signal, select_initial_execution


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="propagate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run an execution from a config file.")
    run_parser.add_argument("--config", required=True, help="Path to the Propagate YAML config.")
    run_parser.add_argument("--execution", help="Execution name to run.")
    run_parser.add_argument("--signal", help="Signal name to activate for this run.")
    run_parser.add_argument("--signal-payload", help="Signal payload as a YAML or JSON mapping. Requires --signal.")
    run_parser.add_argument("--signal-file", help="Path to a YAML or JSON signal document containing 'type' and optional 'payload'.")
    context_parser = subparsers.add_parser("context", help="Manage local context values.")
    context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)
    set_parser = context_subparsers.add_parser("set", help="Store a local context value.")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    get_parser = context_subparsers.add_parser("get", help="Read a local context value.")
    get_parser.add_argument("key")
    return parser


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
    except KeyboardInterrupt:
        LOGGER.error("Execution interrupted.")
        return 130
    parser.error(f"Unsupported command: {args.command}")
    return 2


def dispatch_command(args: argparse.Namespace, working_dir: Path) -> int | None:
    if args.command == "run":
        return run_command(args.config, args.execution, args.signal, args.signal_payload, args.signal_file)
    if args.command == "context":
        if args.context_command == "set":
            return context_set_command(args.key, args.value, working_dir)
        if args.context_command == "get":
            return context_get_command(args.key, working_dir)
    return None


def run_command(
    config_value: str,
    execution_name: str | None,
    signal_name: str | None,
    signal_payload: str | None,
    signal_file: str | None,
) -> int:
    config = load_config(Path(config_value).expanduser())
    active_signal = parse_active_signal(signal_name, signal_payload, signal_file, config.signals)
    log_active_signal(active_signal)
    initial_execution = select_initial_execution(config, execution_name, active_signal)
    run_execution_schedule(
        config,
        initial_execution.name,
        RuntimeContext(
            agent_command=config.agent.command,
            context_sources=config.context_sources,
            active_signal=active_signal,
            initialized_signal_context_dirs=set(),
        ),
    )
    return 0
