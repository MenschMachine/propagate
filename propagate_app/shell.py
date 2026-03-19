from __future__ import annotations

import collections
import getpass
import readline  # noqa: F401 — imported for input() line-editing support
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import zmq

from .config_load import load_config
from .constants import LOGGER
from .errors import PropagateError
from .event_format import format_event_reply
from .message_parser import validate_and_build_payload
from .signal_transport import (
    close_push_socket,
    close_sub_socket,
    connect_push_socket,
    connect_sub_socket,
    pub_socket_address,
    receive_event,
    send_command,
    send_signal,
    socket_address,
)

if TYPE_CHECKING:
    from .models import Config

PROMPT = "propagate> "
_print_lock = threading.Lock()
_QUIT = object()


def shell_command(config_value: str) -> int:
    """Interactive REPL for sending signals to a running propagate instance."""
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
) -> None:
    """Background thread that receives events from the PUB socket."""
    while not stop_event.is_set():
        event = receive_event(sub_socket, timeout_ms=500)
        if event is None:
            continue
        if event.get("event") == "log":
            line = event.get("line", "")
            log_buffer.append(line)
            continue
        text = format_event_reply(event)
        _print_event(text)


def _print_event(text: str) -> None:
    """Print an event above the current input prompt without corrupting it."""
    with _print_lock:
        # Save current input state.
        buf = readline.get_line_buffer()
        # Move to start of line, clear it, print event, then restore prompt.
        sys.stdout.write(f"\r\033[K{text}\n{PROMPT}{buf}")
        sys.stdout.flush()
        readline.redisplay()


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
    LOGGER.info("Sent signal '%s'.", signal_type)
    print(f"Signal '{signal_type}' delivered.")


def _cmd_resume(push_socket: zmq.Socket) -> None:
    send_command(push_socket, "resume")
    LOGGER.info("Sent resume command.")
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
