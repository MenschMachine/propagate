from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import zmq

from .config_load import load_config
from .constants import LOGGER
from .errors import PropagateError
from .models import SignalConfig
from .signal_transport import (
    COORDINATOR_ADDRESS,
    COORDINATOR_PUB_ADDRESS,
    bind_pub_socket,
    bind_pull_socket,
    close_pub_socket,
    close_pull_socket,
    close_push_socket,
    close_sub_socket,
    connect_push_socket,
    connect_sub_socket,
    pub_socket_address,
    receive_event,
    receive_message,
    send_command,
    send_signal,
    socket_address,
)


def _extract_repo_full_names(config) -> set[str]:
    """Extract GitHub-style 'owner/repo' identifiers from repository URLs."""
    names: set[str] = set()
    for repo in config.repositories.values():
        if not repo.url:
            continue
        # Match owner/repo from https or ssh URLs.
        match = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", repo.url)
        if match:
            names.add(match.group(1))
    return names


@dataclass
class WorkerInfo:
    name: str
    config_path: Path
    process: subprocess.Popen
    push_socket: zmq.Socket
    sub_socket: zmq.Socket
    signals: dict[str, SignalConfig] = field(default_factory=dict)
    repositories: set[str] = field(default_factory=set)


class Coordinator:
    def __init__(self, shutdown: threading.Event, worker_stdout_log_path: Path | None = None) -> None:
        self._shutdown = shutdown
        self._workers: dict[str, WorkerInfo] = {}
        self._lock = threading.Lock()
        self._pub_lock = threading.Lock()
        self._pull_socket: zmq.Socket | None = None
        self._pub_socket: zmq.Socket | None = None
        self._proxy_rebuild = threading.Event()
        self._worker_stdout_logger: logging.Logger | None = None
        self._worker_stdout_handler: logging.Handler | None = None
        if worker_stdout_log_path is not None:
            worker_stdout_log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(worker_stdout_log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            logger = logging.getLogger(f"propagate.worker_stdout.{id(self)}")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            logger.addHandler(handler)
            self._worker_stdout_logger = logger
            self._worker_stdout_handler = handler

    def start(self, initial_configs: list[str], resume: bool | str = False, skip: list[str] | None = None) -> None:
        # Bind coordinator sockets first so clients (webhook, telegram, shell)
        # can connect immediately, even before workers are ready.
        self._pull_socket = bind_pull_socket(COORDINATOR_ADDRESS)
        self._pub_socket = bind_pub_socket(COORDINATOR_PUB_ADDRESS)
        LOGGER.info("Coordinator listening on %s", COORDINATOR_ADDRESS)
        LOGGER.info("Coordinator publishing on %s", COORDINATOR_PUB_ADDRESS)

        for config_value in initial_configs:
            config_path = Path(config_value).expanduser().resolve()
            self._load_worker(config_path, resume, skip=skip)

    def run(self) -> None:

        proxy_thread = threading.Thread(target=self._event_proxy, daemon=True)
        proxy_thread.start()

        health_thread = threading.Thread(target=self._health_check, daemon=True)
        health_thread.start()

        try:
            self._main_loop()
        finally:
            self._shutdown_all_workers()
            close_pull_socket(self._pull_socket, COORDINATOR_ADDRESS)
            close_pub_socket(self._pub_socket, COORDINATOR_PUB_ADDRESS)
            self._close_worker_stdout_log()

    def _main_loop(self) -> None:
        while not self._shutdown.is_set():
            result = receive_message(self._pull_socket, block=True, timeout_ms=1000)
            if result is None:
                continue
            kind, name, payload, metadata = result
            try:
                self._dispatch(kind, name, payload, metadata)
            except Exception as exc:
                LOGGER.error("Coordinator dispatch error: %s", exc)

    def _dispatch(self, kind: str, name: str, payload: dict, metadata: dict) -> None:
        if kind == "coordinator":
            action = name
            if action == "list":
                self._handle_list(metadata)
            elif action == "load":
                path = payload.get("path")
                if not path:
                    self._send_response(metadata.get("request_id"), error="Missing 'path' for load.")
                    return
                self._handle_load(Path(path), metadata)
            elif action == "unload":
                project = payload.get("project")
                if not project:
                    self._send_response(metadata.get("request_id"), error="Missing 'project' for unload.")
                    return
                self._handle_unload(project, metadata)
            elif action == "reload":
                project = payload.get("project")
                if not project:
                    self._send_response(metadata.get("request_id"), error="Missing 'project' for reload.")
                    return
                self._handle_reload(project, metadata)
            else:
                self._send_response(metadata.get("request_id"), error=f"Unknown coordinator action '{action}'.")
        elif kind == "signal":
            project = metadata.get("project")
            if project:
                self._forward_signal(project, name, payload, metadata)
            else:
                self._broadcast_signal(name, payload, metadata)
        elif kind == "command":
            project = metadata.get("project")
            if not project:
                self._send_response(metadata.get("request_id"), error="Missing 'project' in metadata for command.")
                return
            self._forward_command(project, name, metadata)

    def _handle_list(self, metadata: dict) -> None:
        request_id = metadata.get("request_id")
        with self._lock:
            projects = []
            for name, worker in self._workers.items():
                status = "running" if worker.process.poll() is None else "dead"
                signals_info = {}
                for sig_name, sig_config in worker.signals.items():
                    fields = {}
                    for field_name, field_cfg in sig_config.payload.items():
                        fields[field_name] = {
                            "field_type": field_cfg.field_type,
                            "required": field_cfg.required,
                        }
                    signals_info[sig_name] = {"payload": fields}
                projects.append({
                    "name": name,
                    "status": status,
                    "config_path": str(worker.config_path),
                    "signals": signals_info,
                })
        self._send_response(request_id, data={"projects": projects})

    def _handle_load(self, path: Path, metadata: dict) -> None:
        request_id = metadata.get("request_id")
        resolved = path.resolve()
        try:
            self._load_worker(resolved)
        except (PropagateError, OSError, TimeoutError) as exc:
            self._send_response(request_id, error=str(exc))
            return
        name = resolved.stem
        self._send_response(request_id, data={"loaded": name})

    def _handle_unload(self, project: str, metadata: dict) -> None:
        request_id = metadata.get("request_id")
        with self._lock:
            worker = self._workers.get(project)
            if worker is None:
                self._send_response(request_id, error=f"No such project '{project}'.")
                return
        LOGGER.info("Coordinator unloading worker '%s'.", project)
        self._stop_worker(project)
        self._send_response(request_id, data={"unloaded": project})

    def _handle_reload(self, project: str, metadata: dict) -> None:
        request_id = metadata.get("request_id")
        with self._lock:
            worker = self._workers.get(project)
            if worker is None:
                self._send_response(request_id, error=f"No such project '{project}'.")
                return
            config_path = worker.config_path
        LOGGER.info("Coordinator initiating reload of worker '%s'.", project)
        self._stop_worker(project)
        try:
            self._load_worker(config_path)
        except (PropagateError, OSError, TimeoutError) as exc:
            self._send_response(request_id, error=f"Reload failed: {exc}")
            return
        LOGGER.info("Coordinator reload of worker '%s' completed.", project)
        self._send_response(request_id, data={"reloaded": project})

    def _forward_signal(self, project: str, signal_type: str, payload: dict, metadata: dict) -> None:
        with self._lock:
            worker = self._workers.get(project)
        if worker is None:
            self._send_response(metadata.get("request_id"), error=f"No such project '{project}'.")
            return
        send_signal(worker.push_socket, signal_type, payload, metadata=metadata)
        LOGGER.debug("Forwarded signal '%s' to worker '%s'.", signal_type, project)

    def _broadcast_signal(self, signal_type: str, payload: dict, metadata: dict) -> None:
        """Route a signal without explicit project. Matches by repository in payload."""
        repo = payload.get("repository", "")
        with self._lock:
            targets = [
                w for w in self._workers.values()
                if w.process.poll() is None and (repo and repo in w.repositories)
            ]
        if not targets:
            LOGGER.debug("No workers match repository '%s' for signal '%s'.", repo, signal_type)
            return
        for worker in targets:
            worker_metadata = {**metadata, "project": worker.name}
            send_signal(worker.push_socket, signal_type, payload, metadata=worker_metadata)
            LOGGER.debug("Broadcast signal '%s' to worker '%s' (repo=%s).", signal_type, worker.name, repo)

    def _forward_command(self, project: str, command: str, metadata: dict) -> None:
        with self._lock:
            worker = self._workers.get(project)
        if worker is None:
            self._send_response(metadata.get("request_id"), error=f"No such project '{project}'.")
            return
        send_command(worker.push_socket, command, metadata=metadata)
        LOGGER.debug("Forwarded command '%s' to worker '%s'.", command, project)

    def _send_response(self, request_id: str | None, data: dict | None = None, error: str | None = None) -> None:
        msg: dict = {"event": "coordinator_response"}
        if request_id:
            msg["request_id"] = request_id
        if data is not None:
            msg["data"] = data
        if error is not None:
            msg["error"] = error
        self._publish(msg)

    def _publish(self, msg: dict) -> None:
        """Thread-safe send on the coordinator PUB socket."""
        with self._pub_lock:
            if self._pub_socket is not None:
                try:
                    self._pub_socket.send_json(msg)
                except zmq.ZMQError:
                    pass

    def _load_worker(self, config_path: Path, resume: bool | str = False, skip: list[str] | None = None) -> None:
        config = load_config(config_path)
        name = config_path.stem
        with self._lock:
            if name in self._workers:
                raise PropagateError(f"Project '{name}' is already loaded.")

        propagate_bin = Path(sys.executable).parent / "propagate"
        cmd = [str(propagate_bin), "serve-worker", "--config", str(config_path)]
        if resume:
            if isinstance(resume, str):
                cmd.extend(["--resume", resume])
            else:
                cmd.append("--resume")
        for skip_value in (skip or []):
            cmd.extend(["--skip", skip_value])

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            text=True,
        )

        try:
            # Use a thread to read the first line so we can enforce a timeout.
            result: list[str] = []

            def _read_first_line() -> None:
                result.append(process.stdout.readline())

            reader = threading.Thread(target=_read_first_line, daemon=True)
            reader.start()
            reader.join(timeout=15)

            if reader.is_alive():
                raise TimeoutError(f"Worker '{name}' did not become ready within 15s.")
            first_line = result[0] if result else ""
            if not first_line:
                rc = process.poll()
                raise TimeoutError(
                    f"Worker '{name}' failed to start (rc={rc})."
                )
            if first_line.strip() != "READY":
                raise TimeoutError(f"Worker '{name}' sent unexpected output: {first_line.strip()}")
        except Exception:
            process.terminate()
            process.wait(timeout=5)
            raise

        # Drain stdout in background so agent/hook output doesn't block the worker.
        threading.Thread(target=self._drain_stdout, args=(process, name), daemon=True).start()

        worker_pull_addr = socket_address(config_path)
        worker_pub_addr = pub_socket_address(config_path)
        push_socket = connect_push_socket(worker_pull_addr)
        sub_socket = connect_sub_socket(worker_pub_addr)

        worker = WorkerInfo(
            name=name,
            config_path=config_path,
            process=process,
            push_socket=push_socket,
            sub_socket=sub_socket,
            signals=config.signals,
            repositories=_extract_repo_full_names(config),
        )
        with self._lock:
            self._workers[name] = worker
        self._proxy_rebuild.set()
        LOGGER.info("Loaded worker '%s' (pid=%d, resume=%s).", name, process.pid, resume)

    def _stop_worker(self, name: str) -> None:
        with self._lock:
            worker = self._workers.pop(name, None)
        if worker is None:
            return
        self._proxy_rebuild.set()
        worker.process.terminate()
        try:
            worker.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            LOGGER.debug("Worker '%s' did not exit in time, sending SIGKILL.", name)
            worker.process.kill()
            worker.process.wait(timeout=5)
        close_push_socket(worker.push_socket)
        close_sub_socket(worker.sub_socket)
        LOGGER.info("Stopped worker '%s'.", name)

    def _event_proxy(self) -> None:
        """Background thread: reads events from all worker SUB sockets, re-publishes on coordinator PUB."""
        poller = zmq.Poller()
        registered: dict[str, zmq.Socket] = {}

        def _rebuild_poller() -> None:
            nonlocal poller, registered
            poller = zmq.Poller()
            registered = {}
            with self._lock:
                for name, worker in self._workers.items():
                    poller.register(worker.sub_socket, zmq.POLLIN)
                    registered[name] = worker.sub_socket

        _rebuild_poller()

        while not self._shutdown.is_set():
            if self._proxy_rebuild.is_set():
                self._proxy_rebuild.clear()
                _rebuild_poller()

            if not registered:
                # No workers — just sleep briefly and check again.
                self._proxy_rebuild.wait(timeout=0.5)
                continue

            try:
                ready = dict(poller.poll(timeout=500))
            except zmq.ZMQError:
                # Socket was closed during poll (worker removed). Rebuild.
                _rebuild_poller()
                continue

            socket_to_name = {sock: name for name, sock in registered.items()}
            for sock, _flag in ready.items():
                try:
                    event = receive_event(sock, timeout_ms=0)
                except zmq.ZMQError:
                    # Socket closed between poll and recv. Will rebuild next iteration.
                    self._proxy_rebuild.set()
                    break
                if event is None:
                    continue
                worker_name = socket_to_name.get(sock)
                if worker_name:
                    event["project"] = worker_name
                self._publish(event)

    def _health_check(self) -> None:
        """Background thread: detect workers that died unexpectedly."""
        notified: set[str] = set()
        while not self._shutdown.is_set():
            time.sleep(2)
            with self._lock:
                dead = [
                    name for name, w in self._workers.items()
                    if w.process.poll() is not None and name not in notified
                ]
            for name in dead:
                LOGGER.error("Worker '%s' died unexpectedly (exit code: %s). Use /reload to restart.",
                    name, self._workers[name].process.poll())
                self._publish({"event": "worker_died", "project": name})
                notified.add(name)

    def _drain_stdout(self, process: subprocess.Popen, name: str) -> None:
        """Forward worker stdout to a transcript file or the propagate logger."""
        try:
            for line in process.stdout:
                message = "[%s] %s"
                text = line.rstrip("\n")
                if self._worker_stdout_logger is not None:
                    self._worker_stdout_logger.info(message, name, text)
                else:
                    LOGGER.info(message, name, text)
        except (OSError, ValueError):
            pass

    def _close_worker_stdout_log(self) -> None:
        if self._worker_stdout_logger is None or self._worker_stdout_handler is None:
            return
        self._worker_stdout_logger.removeHandler(self._worker_stdout_handler)
        self._worker_stdout_handler.close()
        self._worker_stdout_logger = None
        self._worker_stdout_handler = None

    def _shutdown_all_workers(self) -> None:
        with self._lock:
            names = list(self._workers.keys())
        for name in names:
            self._stop_worker(name)
