from __future__ import annotations

import atexit
import collections
import getpass
import queue
import readline
import sys
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import zmq

from .config_load import load_config
from .errors import PropagateError
from .event_format import format_event_reply
from .message_parser import validate_and_build_payload
from .models import SignalConfig, SignalFieldConfig
from .signal_transport import (
    COORDINATOR_ADDRESS,
    COORDINATOR_PUB_ADDRESS,
    close_push_socket,
    close_sub_socket,
    connect_push_socket,
    connect_sub_socket,
    pub_socket_address,
    receive_event,
    send_command,
    send_coordinator_command,
    send_signal,
    socket_address,
)

if TYPE_CHECKING:
    from .models import Config

PROMPT = "propagate> "
_HISTORY_FILE = Path.home() / ".propagate_shell_history"
_print_lock = threading.Lock()
_QUIT = object()


def _load_history() -> None:
    try:
        readline.read_history_file(_HISTORY_FILE)
    except FileNotFoundError:
        pass
    readline.set_history_length(1000)
    atexit.register(readline.write_history_file, _HISTORY_FILE)


class _ShellState:
    """Mutable session state for coordinator-mode shell."""

    def __init__(self) -> None:
        self.active_project: str | None = None
        self.projects: dict[str, dict] = {}  # name -> {"signals": {...}, "status": ..., ...}
        self.response_queue: queue.Queue[dict] = queue.Queue()


def shell_command(config_value: str | None) -> int:
    """Interactive REPL for sending signals to a running propagate instance."""
    _load_history()
    if config_value is not None:
        return _shell_legacy(config_value)
    return _shell_coordinator()


def _shell_coordinator() -> int:
    """Coordinator-mode shell: connect to coordinator sockets."""
    push_socket = connect_push_socket(COORDINATOR_ADDRESS)
    sub_socket = connect_sub_socket(COORDINATOR_PUB_ADDRESS)

    log_buffer: collections.deque[str] = collections.deque(maxlen=500)
    stop_event = threading.Event()
    state = _ShellState()

    listener = threading.Thread(
        target=_event_listener,
        args=(sub_socket, log_buffer, stop_event, state.response_queue),
        daemon=True,
    )
    listener.start()

    try:
        _input_loop_coordinator(push_socket, log_buffer, state)
    finally:
        stop_event.set()
        close_push_socket(push_socket)
        close_sub_socket(sub_socket)

    return 0


def _shell_legacy(config_value: str) -> int:
    """Legacy mode: connect directly to a single config's sockets."""
    config_path = Path(config_value).expanduser()
    config = load_config(config_path)

    address = socket_address(config.config_path)
    push_socket = connect_push_socket(address)

    pub_address = pub_socket_address(config.config_path)
    sub_socket = connect_sub_socket(pub_address)

    log_buffer: collections.deque[str] = collections.deque(maxlen=500)
    stop_event = threading.Event()

    listener = threading.Thread(
        target=_event_listener,
        args=(sub_socket, log_buffer, stop_event),
        daemon=True,
    )
    listener.start()

    try:
        _input_loop(config, push_socket, log_buffer)
    finally:
        stop_event.set()
        close_push_socket(push_socket)
        close_sub_socket(sub_socket)

    return 0


def _event_listener(
    sub_socket: zmq.Socket,
    log_buffer: collections.deque[str],
    stop_event: threading.Event,
    response_queue: queue.Queue[dict] | None = None,
) -> None:
    """Background thread that receives events from the PUB socket."""
    while not stop_event.is_set():
        event = receive_event(sub_socket, timeout_ms=500)
        if event is None:
            continue
        if event.get("event") == "log":
            line = event.get("line", "")
            project = event.get("project")
            if project:
                line = f"[{project}] {line}"
            log_buffer.append(line)
            continue
        if event.get("event") == "coordinator_response":
            if response_queue is not None:
                response_queue.put(event)
            continue
        project = event.get("project")
        text = format_event_reply(event)
        if project:
            text = f"[{project}] {text}"
        _print_event(text)


def _print_event(text: str) -> None:
    """Print an event above the current input prompt without corrupting it."""
    with _print_lock:
        buf = readline.get_line_buffer()
        sys.stdout.write(f"\r\033[K{text}\n{PROMPT}{buf}")
        sys.stdout.flush()
        readline.redisplay()


def _wait_for_response(response_queue: queue.Queue[dict], request_id: str, timeout: float = 10.0) -> dict | None:
    """Wait for a coordinator_response matching request_id from the event listener queue."""
    import time
    deadline = time.monotonic() + timeout
    stashed: list[dict] = []
    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                event = response_queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if event.get("request_id") == request_id:
                return event
            stashed.append(event)
        return None
    finally:
        for item in stashed:
            response_queue.put(item)


# ---------------------------------------------------------------------------
# Coordinator-mode input loop and commands
# ---------------------------------------------------------------------------


def _input_loop_coordinator(
    push_socket: zmq.Socket,
    log_buffer: collections.deque[str],
    state: _ShellState,
) -> None:
    """Read user commands in coordinator mode."""
    print("Type /help for available commands, /quit to exit.")
    while True:
        try:
            line = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            print()
            break
        line = line.strip()
        if not line:
            continue
        try:
            result = _dispatch_coordinator(line, push_socket, log_buffer, state)
            if result is _QUIT:
                break
        except PropagateError as exc:
            print(f"Error: {exc}")
        except ValueError as exc:
            print(f"Error: {exc}")


def _dispatch_coordinator(
    line: str,
    push_socket: zmq.Socket,
    log_buffer: collections.deque[str],
    state: _ShellState,
) -> object | None:
    parts = line.split(None, 1)
    cmd = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if cmd in ("/quit", "/exit"):
        return _QUIT

    if cmd == "/help":
        _cmd_help_coordinator(state)
    elif cmd == "/list":
        _cmd_list(push_socket, state)
    elif cmd == "/load":
        _cmd_load(rest, push_socket, state)
    elif cmd == "/unload":
        _cmd_unload(rest, push_socket, state)
    elif cmd == "/reload":
        _cmd_reload(rest, push_socket, state)
    elif cmd == "/project":
        _cmd_project(rest, state)
    elif cmd == "/signals":
        _cmd_signals_coordinator(state)
    elif cmd == "/signal":
        _cmd_signal_coordinator(rest, push_socket, state)
    elif cmd == "/resume":
        _cmd_resume_coordinator(push_socket, state)
    elif cmd == "/logs":
        _cmd_logs(rest, log_buffer)
    else:
        print(f"Unknown command: {cmd} (type /help for available commands)")
    return None


def _cmd_help_coordinator(state: _ShellState) -> None:
    print(
        "Commands:\n"
        "  /list                           — list loaded projects\n"
        "  /load <path>                    — load a config as a new project\n"
        "  /unload <name>                  — stop and unload a project\n"
        "  /reload <name>                  — reload a project\n"
        "  /project [name]                 — show or set active project\n"
        "  /signal <signal> [key:val ...]  — send a signal (requires active project)\n"
        "  /resume                         — resume a failed run (requires active project)\n"
        "  /signals                        — list available signals\n"
        "  /logs [N]                       — show last N log lines (default 20)\n"
        "  /help                           — show this message\n"
        "  /quit, /exit                    — exit the shell"
    )


def _cmd_list(push_socket: zmq.Socket, state: _ShellState) -> None:
    request_id = str(uuid.uuid4())
    send_coordinator_command(push_socket, "list", metadata={"request_id": request_id})
    resp = _wait_for_response(state.response_queue, request_id)
    if resp is None:
        print("No response from coordinator (timeout).")
        return
    if "error" in resp:
        print(f"Error: {resp['error']}")
        return
    data = resp.get("data", {})
    projects = data.get("projects", [])
    _update_cached_projects(state, projects)
    if not projects:
        print("No projects loaded.")
        return
    for proj in projects:
        marker = " (active)" if proj["name"] == state.active_project else ""
        sig_names = ", ".join(sorted(proj.get("signals", {}))) or "(none)"
        print(f"  {proj['name']} [{proj['status']}]{marker} — signals: {sig_names}")


def _cmd_load(rest: str, push_socket: zmq.Socket, state: _ShellState) -> None:
    if not rest.strip():
        print("Usage: /load <path>")
        return
    path = Path(rest.strip()).expanduser().resolve()
    request_id = str(uuid.uuid4())
    send_coordinator_command(push_socket, "load", metadata={"request_id": request_id}, path=str(path))
    resp = _wait_for_response(state.response_queue, request_id)
    if resp is None:
        print("No response from coordinator (timeout).")
        return
    if "error" in resp:
        print(f"Error: {resp['error']}")
        return
    loaded = resp.get("data", {}).get("loaded", "")
    state.active_project = loaded
    _refresh_projects(push_socket, state)
    print(f"Loaded and activated project '{loaded}'.")


def _cmd_unload(rest: str, push_socket: zmq.Socket, state: _ShellState) -> None:
    name = rest.strip()
    if not name:
        print("Usage: /unload <name>")
        return
    request_id = str(uuid.uuid4())
    send_coordinator_command(push_socket, "unload", metadata={"request_id": request_id}, project=name)
    resp = _wait_for_response(state.response_queue, request_id)
    if resp is None:
        print("No response from coordinator (timeout).")
        return
    if "error" in resp:
        print(f"Error: {resp['error']}")
        return
    print(f"Unloaded project '{name}'.")
    if state.active_project == name:
        state.active_project = None


def _cmd_reload(rest: str, push_socket: zmq.Socket, state: _ShellState) -> None:
    name = rest.strip()
    if not name:
        print("Usage: /reload <name>")
        return
    request_id = str(uuid.uuid4())
    send_coordinator_command(push_socket, "reload", metadata={"request_id": request_id}, project=name)
    resp = _wait_for_response(state.response_queue, request_id)
    if resp is None:
        print("No response from coordinator (timeout).")
        return
    if "error" in resp:
        print(f"Error: {resp['error']}")
        return
    _refresh_projects(push_socket, state)
    print(f"Reloaded project '{name}'.")


def _cmd_project(rest: str, state: _ShellState) -> None:
    name = rest.strip()
    if not name:
        if state.active_project:
            print(f"Active project: {state.active_project}")
        else:
            print("No active project. Use /project <name> to set one, or /list to see available projects.")
        return
    if name not in state.projects:
        available = ", ".join(sorted(state.projects)) if state.projects else "(none — use /list to refresh)"
        print(f"Unknown project '{name}'. Available: {available}")
        return
    state.active_project = name
    print(f"Switched to project '{name}'.")


def _cmd_signals_coordinator(state: _ShellState) -> None:
    if not state.projects:
        print("No projects loaded. Use /list to refresh.")
        return
    project_name = state.active_project
    if project_name is None:
        if len(state.projects) == 1:
            project_name = next(iter(state.projects))
        else:
            print("Multiple projects loaded. Use /project <name> to select one first.")
            return
    proj = state.projects.get(project_name)
    if proj is None:
        print(f"Project '{project_name}' not found. Use /list to refresh.")
        return
    signals_info = proj.get("signals", {})
    if not signals_info:
        print("No signals configured.")
        return
    lines: list[str] = [f"[{project_name}] Available signals:"]
    for sig_name in sorted(signals_info):
        lines.append(f"  {sig_name}")
        fields = signals_info[sig_name].get("payload", {})
        for field_name, field_info in fields.items():
            if field_name == "sender":
                continue
            req = ", required" if field_info.get("required") else ""
            lines.append(f"    {field_name} ({field_info.get('field_type', 'string')}{req})")
    print("\n".join(lines))


def _cmd_signal_coordinator(rest: str, push_socket: zmq.Socket, state: _ShellState) -> None:
    if not rest:
        print("Usage: /signal <signal> [key:val ...]")
        return

    project_name = state.active_project
    if project_name is None:
        if len(state.projects) == 1:
            project_name = next(iter(state.projects))
        else:
            print("No active project. Use /project <name> to select one first.")
            return

    proj = state.projects.get(project_name)
    if proj is None:
        print(f"Project '{project_name}' not found. Use /list to refresh.")
        return

    parts = rest.split(None, 1)
    signal_type = parts[0]
    remaining = parts[1] if len(parts) > 1 else ""

    signals_info = proj.get("signals", {})
    if signal_type not in signals_info:
        defined = ", ".join(sorted(signals_info))
        print(f"Signal '{signal_type}' not defined (defined: {defined}).")
        return

    # Reconstruct a SignalConfig for validation.
    sig_info = signals_info[signal_type]
    payload_fields = {}
    for fname, finfo in sig_info.get("payload", {}).items():
        payload_fields[fname] = SignalFieldConfig(
            field_type=finfo.get("field_type", "string"),
            required=finfo.get("required", False),
        )
    signal_config = SignalConfig(name=signal_type, payload=payload_fields)

    payload, errors = validate_and_build_payload(remaining, signal_config)
    if errors:
        print(errors[0])
        return

    if "sender" in payload_fields:
        payload["sender"] = getpass.getuser()

    send_signal(push_socket, signal_type, payload, metadata={"project": project_name})
    print(f"Signal '{signal_type}' delivered to '{project_name}'.")


def _cmd_resume_coordinator(push_socket: zmq.Socket, state: _ShellState) -> None:
    project_name = state.active_project
    if project_name is None:
        if len(state.projects) == 1:
            project_name = next(iter(state.projects))
        else:
            print("No active project. Use /project <name> to select one first.")
            return
    send_command(push_socket, "resume", metadata={"project": project_name})
    print(f"Resume command delivered to '{project_name}'.")


def _refresh_projects(push_socket: zmq.Socket, state: _ShellState) -> None:
    """Silently fetch the project list from the coordinator to update the cache."""
    request_id = str(uuid.uuid4())
    send_coordinator_command(push_socket, "list", metadata={"request_id": request_id})
    resp = _wait_for_response(state.response_queue, request_id, timeout=5.0)
    if resp is not None and "error" not in resp:
        projects = resp.get("data", {}).get("projects", [])
        _update_cached_projects(state, projects)


def _update_cached_projects(state: _ShellState, projects: list[dict]) -> None:
    state.projects = {p["name"]: p for p in projects}
    if state.active_project and state.active_project not in state.projects:
        state.active_project = None


# ---------------------------------------------------------------------------
# Legacy (direct config) mode — unchanged interface
# ---------------------------------------------------------------------------


def _input_loop(config: Config, push_socket: zmq.Socket, log_buffer: collections.deque[str]) -> None:
    """Read user commands in a loop."""
    print("Type /help for available commands, /quit to exit.")
    while True:
        try:
            line = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            print()
            break
        line = line.strip()
        if not line:
            continue
        try:
            result = _dispatch(line, config, push_socket, log_buffer)
            if result is _QUIT:
                break
        except PropagateError as exc:
            print(f"Error: {exc}")
        except ValueError as exc:
            print(f"Error: {exc}")


def _dispatch(
    line: str,
    config: Config,
    push_socket: zmq.Socket,
    log_buffer: collections.deque[str],
) -> object | None:
    """Dispatch a single user command.  Returns ``_QUIT`` to exit."""
    parts = line.split(None, 1)
    cmd = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if cmd in ("/quit", "/exit"):
        return _QUIT

    if cmd == "/help":
        _cmd_help(config)
    elif cmd == "/signals":
        _cmd_signals(config)
    elif cmd == "/signal":
        _cmd_signal(rest, config, push_socket)
    elif cmd == "/resume":
        _cmd_resume(push_socket)
    elif cmd == "/logs":
        _cmd_logs(rest, log_buffer)
    else:
        print(f"Unknown command: {cmd} (type /help for available commands)")
    return None


def _cmd_help(config: Config) -> None:
    names = sorted(config.signals)
    signals_line = ", ".join(names) if names else "(none)"
    print(
        "Commands:\n"
        "  /signal <signal> [key:val ...]  — send a signal\n"
        "  /resume                         — resume a failed run\n"
        "  /signals                        — list available signals\n"
        "  /logs [N]                       — show last N log lines (default 20)\n"
        "  /help                           — show this message\n"
        "  /quit, /exit                    — exit the shell\n"
        f"\nAvailable signals: {signals_line}"
    )


def _cmd_signals(config: Config) -> None:
    names = sorted(config.signals)
    if not names:
        print("No signals configured.")
        return
    lines: list[str] = ["Available signals:"]
    for name in names:
        lines.append(f"  {name}")
        sig = config.signals[name]
        for field_name, field_cfg in sig.payload.items():
            if field_name == "sender":
                continue
            req = ", required" if field_cfg.required else ""
            lines.append(f"    {field_name} ({field_cfg.field_type}{req})")
    print("\n".join(lines))


def _cmd_signal(rest: str, config: Config, push_socket: zmq.Socket) -> None:
    if not rest:
        print("Usage: /signal <signal> [key:val ...]")
        return

    parts = rest.split(None, 1)
    signal_type = parts[0]
    remaining = parts[1] if len(parts) > 1 else ""

    if signal_type not in config.signals:
        defined = ", ".join(sorted(config.signals))
        print(f"Signal '{signal_type}' not defined in config (defined: {defined}).")
        return

    signal_config = config.signals[signal_type]

    payload, errors = validate_and_build_payload(remaining, signal_config)
    if errors:
        print(errors[0])
        return

    if "sender" in signal_config.payload:
        payload["sender"] = getpass.getuser()

    send_signal(push_socket, signal_type, payload)
    print(f"Signal '{signal_type}' delivered.")


def _cmd_resume(push_socket: zmq.Socket) -> None:
    send_command(push_socket, "resume")
    print("Resume command delivered.")


def _cmd_logs(rest: str, log_buffer: collections.deque[str]) -> None:
    n = 20
    if rest:
        try:
            n = int(rest)
        except ValueError:
            print("Usage: /logs [N] — N must be a number.")
            return

    items = list(log_buffer)
    lines = items[-n:] if n < len(items) else items
    if not lines:
        print("No logs available.")
        return
    print("\n".join(lines))
