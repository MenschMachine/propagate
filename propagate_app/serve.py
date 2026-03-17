from __future__ import annotations

import collections
import logging
import signal as signal_module
import threading
from pathlib import Path

import zmq

from .config_load import load_config
from .constants import LOGGER
from .errors import PropagateError
from .log_buffer import ZmqLogHandler
from .models import ActiveSignal, Config, ExecutionScheduleState, RunState, RuntimeContext
from .run_state import load_run_state, state_file_path
from .scheduler import run_execution_schedule
from .signal_transport import (
    bind_pub_socket,
    bind_pull_socket,
    close_pub_socket,
    close_pull_socket,
    pub_socket_address,
    publish_event,
    receive_message,
    socket_address,
)
from .signals import log_active_signal, select_initial_execution, validate_signal_payload


class _RunLogBuffer(logging.Handler):
    """Ring buffer that captures the last *maxlen* log messages."""

    def __init__(self, maxlen: int = 3) -> None:
        super().__init__(level=logging.INFO)
        self.records_buffer: collections.deque[str] = collections.deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        self.records_buffer.append(self.format(record))

    def messages(self) -> list[str]:
        return list(self.records_buffer)


def _run_with_event_publish(
    pub_socket: zmq.Socket | None,
    signal_type: str,
    metadata: dict,
    fn: collections.abc.Callable[[], None],
) -> None:
    """Run *fn*, publish ``run_completed`` or ``run_failed`` on the PUB socket."""
    log_buffer = _RunLogBuffer()
    LOGGER.addHandler(log_buffer)
    try:
        fn()
    except Exception:
        if pub_socket is not None:
            publish_event(pub_socket, "run_failed", {
                "signal_type": signal_type,
                "metadata": metadata,
                "messages": log_buffer.messages(),
            })
        raise
    finally:
        LOGGER.removeHandler(log_buffer)

    if pub_socket is not None:
        publish_event(pub_socket, "run_completed", {
            "signal_type": signal_type,
            "metadata": metadata,
            "messages": log_buffer.messages(),
        })


def serve_command(config_value: str) -> int:
    config_path = Path(config_value).expanduser()
    config = load_config(config_path)
    address = socket_address(config.config_path)
    signal_socket = bind_pull_socket(address)
    LOGGER.info("Listening for signals on %s", address)

    pub_address = pub_socket_address(config.config_path)
    pub_socket = bind_pub_socket(pub_address)
    LOGGER.info("Publishing events on %s", pub_address)

    zmq_log_handler = ZmqLogHandler(pub_socket)
    zmq_log_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    logging.getLogger().addHandler(zmq_log_handler)

    shutdown = threading.Event()

    def handle_shutdown(signum: int, frame: object) -> None:
        if shutdown.is_set():
            LOGGER.info("Forced shutdown.")
            raise KeyboardInterrupt
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
                _resume_run(config, signal_socket, pub_socket)
            except PropagateError as error:
                LOGGER.error("Resume failed: %s", error)
        _serve_loop(config, signal_socket, shutdown, pub_socket)
        return 0
    finally:
        logging.getLogger().removeHandler(zmq_log_handler)
        close_pull_socket(signal_socket, address)
        close_pub_socket(pub_socket, pub_address)
        signal_module.signal(signal_module.SIGTERM, previous_sigterm)
        signal_module.signal(signal_module.SIGINT, previous_sigint)


def _resume_run(
    config: Config,
    signal_socket: zmq.Socket | None,
    pub_socket: zmq.Socket | None = None,
    metadata: dict | None = None,
) -> None:
    run_state = load_run_state(config.config_path)
    active_signal = run_state.active_signal
    log_active_signal(active_signal)
    initialized_dirs = set(run_state.initialized_signal_context_dirs)
    # Prefer metadata from the incoming message (e.g. the user who sent /resume)
    # over whatever was saved in the state file from the original signal.
    run_metadata = metadata if metadata else run_state.metadata
    signal_type = active_signal.signal_type if active_signal else "unknown"

    def do_run() -> None:
        run_execution_schedule(
            config,
            run_state.initial_execution,
            RuntimeContext(
                agent_command=config.agent.command,
                context_sources=config.context_sources,
                active_signal=active_signal,
                initialized_signal_context_dirs=initialized_dirs,
                signal_socket=signal_socket,
                config_dir=config.config_path.parent,
            ),
            run_state=run_state,
            signal_socket=signal_socket,
        )

    _run_with_event_publish(pub_socket, signal_type, run_metadata, do_run)


def _serve_loop(
    config: Config,
    signal_socket: zmq.Socket,
    shutdown: threading.Event,
    pub_socket: zmq.Socket | None = None,
) -> None:
    LOGGER.info("Serve loop started, waiting for signals.")
    while not shutdown.is_set():
        result = receive_message(signal_socket, block=True, timeout_ms=1000)
        if result is None:
            continue
        kind, name, payload, metadata = result
        try:
            if kind == "command":
                _handle_command(config, name, signal_socket, pub_socket, metadata)
            else:
                _handle_incoming_signal(config, name, payload, signal_socket, pub_socket, metadata)
        except KeyboardInterrupt:
            LOGGER.info("Interrupted during run, exiting serve loop.")
            return
        except PropagateError as error:
            LOGGER.error("Run failed for %s '%s': %s", kind, name, error)
    LOGGER.info("Shutdown requested, exiting serve loop.")


def _handle_command(
    config: Config,
    command: str,
    signal_socket: zmq.Socket,
    pub_socket: zmq.Socket | None = None,
    metadata: dict | None = None,
) -> None:
    if command == "resume":
        if state_file_path(config.config_path).exists():
            LOGGER.info("Received resume command, resuming previous run.")
            _resume_run(config, signal_socket, pub_socket, metadata=metadata)
        else:
            LOGGER.warning("Received resume command but no state file found; nothing to resume.")
            if pub_socket is not None:
                publish_event(pub_socket, "command_failed", {
                    "command": "resume",
                    "message": "No state file found; nothing to resume.",
                    "metadata": metadata or {},
                })
    else:
        LOGGER.warning("Received unknown command '%s'; ignoring.", command)


def _handle_incoming_signal(
    config: Config,
    signal_type: str,
    payload: dict,
    signal_socket: zmq.Socket,
    pub_socket: zmq.Socket | None = None,
    metadata: dict | None = None,
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
    run_metadata = metadata or {}
    run_state = RunState(
        config_path=config.config_path,
        initial_execution=initial_execution.name,
        schedule=ExecutionScheduleState(active_names=set(), completed_names=set()),
        active_signal=active_signal,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
        metadata=run_metadata,
    )

    def do_run() -> None:
        run_execution_schedule(
            config,
            initial_execution.name,
            RuntimeContext(
                agent_command=config.agent.command,
                context_sources=config.context_sources,
                active_signal=active_signal,
                initialized_signal_context_dirs=set(),
                signal_socket=signal_socket,
                config_dir=config.config_path.parent,
            ),
            run_state=run_state,
            signal_socket=signal_socket,
        )

    _run_with_event_publish(pub_socket, signal_type, run_metadata, do_run)
    LOGGER.info("Completed run for signal '%s'.", signal_type)
