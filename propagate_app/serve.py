from __future__ import annotations

import collections
import logging
import signal as signal_module
import threading
from pathlib import Path

import zmq

from .config_load import load_config
from .constants import LOGGER, set_project_stem
from .errors import PropagateError
from .log_buffer import ZmqLogHandler
from .models import ActiveSignal, Config, RunState, RuntimeContext
from .run_state import apply_forced_resume_if_targeted, load_run_state, state_file_path
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
    LOGGER.logger.addHandler(log_buffer)
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
        LOGGER.logger.removeHandler(log_buffer)

    if pub_socket is not None:
        publish_event(pub_socket, "run_completed", {
            "signal_type": signal_type,
            "metadata": metadata,
            "messages": log_buffer.messages(),
        })


def _bind_worker_sockets(config: Config) -> tuple[zmq.Socket, str, zmq.Socket, str]:
    """Bind PULL + PUB sockets for a single config. Returns (pull, pull_addr, pub, pub_addr)."""
    address = socket_address(config.config_path)
    signal_socket = bind_pull_socket(address)
    LOGGER.info("Listening for signals on %s", address)

    pub_address = pub_socket_address(config.config_path)
    pub_socket = bind_pub_socket(pub_address)
    LOGGER.info("Publishing events on %s", pub_address)
    return signal_socket, address, pub_socket, pub_address


def _run_worker_loop(
    config: Config,
    signal_socket: zmq.Socket,
    address: str,
    pub_socket: zmq.Socket,
    pub_address: str,
    shutdown: threading.Event,
    resume: bool | str = False,
    skip_executions: set[str] | None = None,
    skip_tasks: dict[str, set[str]] | None = None,
) -> None:
    """Attach log handler, resume if needed, enter serve loop. Cleans up on exit."""
    zmq_log_handler = ZmqLogHandler(pub_socket)
    zmq_log_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    thread_ident = threading.current_thread().ident

    class _ThreadFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return record.thread == thread_ident

    if threading.current_thread() is not threading.main_thread():
        zmq_log_handler.addFilter(_ThreadFilter())

    logging.getLogger().addHandler(zmq_log_handler)

    resume_target = resume if isinstance(resume, str) else None
    config_path = config.config_path
    LOGGER.info("Worker starting (resume=%s, state_exists=%s).", resume, state_file_path(config_path).exists())
    try:
        if resume and not state_file_path(config_path).exists():
            LOGGER.warning("--resume requested but no state file found; starting fresh.")
        elif state_file_path(config_path).exists():
            if resume_target:
                apply_forced_resume_if_targeted(config_path, config, resume_target)
            else:
                LOGGER.info("Found existing state file, resuming previous run.")
            try:
                _resume_run(config, signal_socket, pub_socket, skip_executions=skip_executions, skip_tasks=skip_tasks)
            except PropagateError as error:
                LOGGER.error("Resume failed: %s", error)
        LOGGER.info("Worker entering serve loop.")
        _serve_loop(config, signal_socket, shutdown, pub_socket, skip_executions=skip_executions, skip_tasks=skip_tasks)
    finally:
        logging.getLogger().removeHandler(zmq_log_handler)
        close_pull_socket(signal_socket, address)
        close_pub_socket(pub_socket, pub_address)


def serve_worker_command(config_value: str, resume: bool | str = False, skip: list[str] | None = None) -> int:
    """Entry point for the ``serve-worker`` subcommand (spawned by coordinator)."""
    import sys

    config_path = Path(config_value).expanduser()
    config = load_config(config_path)
    set_project_stem(config.config_path.stem)
    shutdown = threading.Event()

    def handle_shutdown(signum: int, frame: object) -> None:
        if shutdown.is_set():
            raise KeyboardInterrupt
        LOGGER.debug("Worker received shutdown signal.")
        shutdown.set()

    signal_module.signal(signal_module.SIGTERM, handle_shutdown)
    signal_module.signal(signal_module.SIGINT, handle_shutdown)

    from .cli import parse_and_validate_skip

    skip_executions, skip_tasks = parse_and_validate_skip(skip or [], config)
    signal_socket, address, pub_socket, pub_address = _bind_worker_sockets(config)
    # Tell the coordinator we are ready.
    sys.stdout.write("READY\n")
    sys.stdout.flush()
    try:
        _run_worker_loop(config, signal_socket, address, pub_socket, pub_address, shutdown, resume, skip_executions=skip_executions, skip_tasks=skip_tasks)
    except KeyboardInterrupt:
        pass
    return 0


def serve_command(
    config_values: list[str],
    resume: bool | str = False,
    worker_stdout_log: str | None = None,
    skip: list[str] | None = None,
) -> int:
    from .coordinator import Coordinator

    # Validate config stems are unique upfront.
    seen_stems: dict[str, str] = {}
    for cv in config_values:
        config_path = Path(cv).expanduser()
        stem = config_path.stem
        if stem in seen_stems:
            raise PropagateError(
                f"Duplicate config name '{stem}' from '{cv}' and '{seen_stems[stem]}'. "
                "Config filenames must be unique."
            )
        seen_stems[stem] = cv

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
        worker_stdout_log_path = None
        if worker_stdout_log:
            worker_stdout_log_path = Path(worker_stdout_log).expanduser().resolve()
        coordinator = Coordinator(shutdown, worker_stdout_log_path=worker_stdout_log_path)
        coordinator.start(config_values, resume, skip=skip)
        coordinator.run()
        return 0
    finally:
        signal_module.signal(signal_module.SIGTERM, previous_sigterm)
        signal_module.signal(signal_module.SIGINT, previous_sigint)


def _resume_run(
    config: Config,
    signal_socket: zmq.Socket | None,
    pub_socket: zmq.Socket | None = None,
    metadata: dict | None = None,
    skip_executions: set[str] | None = None,
    skip_tasks: dict[str, set[str]] | None = None,
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
                agents=config.agent.agents,
                default_agent=config.agent.default_agent,
                context_sources=config.context_sources,
                active_signal=active_signal,
                initialized_signal_context_dirs=initialized_dirs,
                signal_configs=config.signals,
                signal_socket=signal_socket,
                config_dir=config.config_path.parent,
                pub_socket=pub_socket,
                metadata=run_metadata,
            ),
            run_state=run_state,
            signal_socket=signal_socket,
            skip_executions=skip_executions,
            skip_tasks=skip_tasks,
        )

    _run_with_event_publish(pub_socket, signal_type, run_metadata, do_run)


def _serve_loop(
    config: Config,
    signal_socket: zmq.Socket,
    shutdown: threading.Event,
    pub_socket: zmq.Socket | None = None,
    skip_executions: set[str] | None = None,
    skip_tasks: dict[str, set[str]] | None = None,
) -> None:
    LOGGER.info("Serve loop started, waiting for signals.")
    while not shutdown.is_set():
        result = receive_message(signal_socket, block=True, timeout_ms=1000)
        if result is None:
            continue
        kind, name, payload, metadata = result
        try:
            if kind == "command":
                _handle_command(config, name, signal_socket, pub_socket, metadata, skip_executions=skip_executions, skip_tasks=skip_tasks)
            else:
                _handle_incoming_signal(config, name, payload, signal_socket, pub_socket, metadata, skip_executions=skip_executions, skip_tasks=skip_tasks)
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
    skip_executions: set[str] | None = None,
    skip_tasks: dict[str, set[str]] | None = None,
) -> None:
    if command == "resume":
        if state_file_path(config.config_path).exists():
            LOGGER.info("Received resume command, resuming previous run.")
            _resume_run(config, signal_socket, pub_socket, metadata=metadata, skip_executions=skip_executions, skip_tasks=skip_tasks)
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
    skip_executions: set[str] | None = None,
    skip_tasks: dict[str, set[str]] | None = None,
) -> None:
    if signal_type not in config.signals:
        LOGGER.info("Received unknown signal '%s'; ignoring.", signal_type)
        return
    signal_config = config.signals[signal_type]
    try:
        validate_signal_payload(signal_config, payload)
    except PropagateError as error:
        LOGGER.warning("Received signal '%s' with invalid payload: %s; ignoring.", signal_type, error)
        return
    active_signal = ActiveSignal(signal_type=signal_type, payload=payload, source="external")
    LOGGER.info("Received signal '%s', selecting execution.", signal_type)
    try:
        initial_execution = select_initial_execution(config, None, active_signal)
    except PropagateError as error:
        LOGGER.info("Signal '%s' ignored: %s", signal_type, error)
        return
    run_metadata = metadata or {}
    run_state = RunState(
        config_path=config.config_path,
        initial_execution=initial_execution.name,
        executions={},
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
                agents=config.agent.agents,
                default_agent=config.agent.default_agent,
                context_sources=config.context_sources,
                active_signal=active_signal,
                initialized_signal_context_dirs=set(),
                signal_configs=config.signals,
                signal_socket=signal_socket,
                config_dir=config.config_path.parent,
                pub_socket=pub_socket,
                metadata=run_metadata,
            ),
            run_state=run_state,
            signal_socket=signal_socket,
            skip_executions=skip_executions,
            skip_tasks=skip_tasks,
        )

    _run_with_event_publish(pub_socket, signal_type, run_metadata, do_run)
    LOGGER.info("Completed run for signal '%s'.", signal_type)
