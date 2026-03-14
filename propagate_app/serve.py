from __future__ import annotations

import signal as signal_module
import threading
from pathlib import Path

import zmq

from .config_load import load_config
from .constants import LOGGER
from .errors import PropagateError
from .models import ActiveSignal, Config, ExecutionScheduleState, RunState, RuntimeContext
from .run_state import load_run_state, state_file_path
from .scheduler import run_execution_schedule
from .signal_transport import bind_pull_socket, close_pull_socket, receive_signal, socket_address
from .signals import log_active_signal, select_initial_execution, validate_signal_payload


def serve_command(config_value: str) -> int:
    config_path = Path(config_value).expanduser()
    config = load_config(config_path)
    address = socket_address(config.config_path)
    signal_socket = bind_pull_socket(address)
    LOGGER.info("Listening for signals on %s", address)

    shutdown = threading.Event()

    def handle_shutdown(signum: int, frame: object) -> None:
        LOGGER.info("Received shutdown signal, will exit after current operation.")
        shutdown.set()

    previous_sigterm = signal_module.getsignal(signal_module.SIGTERM)
    previous_sigint = signal_module.getsignal(signal_module.SIGINT)
    signal_module.signal(signal_module.SIGTERM, handle_shutdown)
    signal_module.signal(signal_module.SIGINT, handle_shutdown)
    try:
        if state_file_path(config_path).exists():
            LOGGER.info("Found existing state file, resuming previous run.")
            try:
                _resume_run(config, signal_socket)
            except PropagateError as error:
                LOGGER.error("Resume failed: %s", error)
        _serve_loop(config, signal_socket, shutdown)
        return 0
    finally:
        close_pull_socket(signal_socket, address)
        signal_module.signal(signal_module.SIGTERM, previous_sigterm)
        signal_module.signal(signal_module.SIGINT, previous_sigint)


def _resume_run(config: Config, signal_socket: zmq.Socket | None) -> None:
    run_state = load_run_state(config.config_path)
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
        signal_socket=signal_socket,
    )


def _serve_loop(config: Config, signal_socket: zmq.Socket, shutdown: threading.Event) -> None:
    LOGGER.info("Serve loop started, waiting for signals.")
    while not shutdown.is_set():
        result = receive_signal(signal_socket, block=True, timeout_ms=1000)
        if result is None:
            continue
        signal_type, payload = result
        try:
            _handle_incoming_signal(config, signal_type, payload, signal_socket)
        except KeyboardInterrupt:
            LOGGER.info("Interrupted during run, exiting serve loop.")
            return
        except PropagateError as error:
            LOGGER.error("Run failed for signal '%s': %s", signal_type, error)
    LOGGER.info("Shutdown requested, exiting serve loop.")


def _handle_incoming_signal(
    config: Config,
    signal_type: str,
    payload: dict,
    signal_socket: zmq.Socket,
) -> None:
    if signal_type not in config.signals:
        LOGGER.warning("Received unknown signal '%s'; ignoring.", signal_type)
        return
    signal_config = config.signals[signal_type]
    try:
        validate_signal_payload(signal_config, payload)
    except PropagateError as error:
        LOGGER.warning("Received signal '%s' with invalid payload: %s; ignoring.", signal_type, error)
        return
    active_signal = ActiveSignal(signal_type=signal_type, payload=payload, source="external")
    LOGGER.info("Received signal '%s', selecting execution.", signal_type)
    initial_execution = select_initial_execution(config, None, active_signal)
    run_state = RunState(
        config_path=config.config_path,
        initial_execution=initial_execution.name,
        schedule=ExecutionScheduleState(active_names=set(), completed_names=set()),
        active_signal=active_signal,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
    )
    run_execution_schedule(
        config,
        initial_execution.name,
        RuntimeContext(
            agent_command=config.agent.command,
            context_sources=config.context_sources,
            active_signal=active_signal,
            initialized_signal_context_dirs=set(),
        ),
        run_state=run_state,
        signal_socket=signal_socket,
    )
    LOGGER.info("Completed run for signal '%s'.", signal_type)
