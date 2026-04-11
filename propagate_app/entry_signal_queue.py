from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .errors import PropagateError
from .models import ActiveSignal

QUEUE_VERSION = 1


@dataclass(frozen=True)
class QueuedEntrySignal:
    sequence: int
    initial_execution: str
    active_signal: ActiveSignal
    metadata: dict
    enqueued_at: str


def queue_file_path(config_path: Path) -> Path:
    resolved = config_path.resolve()
    return resolved.parent / f".propagate-queue-{resolved.stem}.yaml"


def load_entry_signal_queue(config_path: Path) -> list[QueuedEntrySignal]:
    _, items = _load_queue_document(config_path)
    return items


def enqueue_entry_signal(
    config_path: Path,
    *,
    initial_execution: str,
    active_signal: ActiveSignal,
    metadata: dict | None = None,
) -> QueuedEntrySignal:
    next_sequence, items = _load_queue_document(config_path)
    queued = QueuedEntrySignal(
        sequence=next_sequence,
        initial_execution=initial_execution,
        active_signal=active_signal,
        metadata=dict(metadata or {}),
        enqueued_at=datetime.now(UTC).isoformat(),
    )
    items.append(queued)
    _write_queue_document(config_path, next_sequence + 1, items)
    return queued


def dequeue_entry_signal(config_path: Path) -> QueuedEntrySignal | None:
    next_sequence, items = _load_queue_document(config_path)
    if not items:
        return None
    popped = items.pop(0)
    _write_queue_document(config_path, next_sequence, items)
    return popped


def clear_entry_signal_queue(config_path: Path) -> None:
    target = queue_file_path(config_path)
    if target.exists():
        target.unlink()


def _load_queue_document(config_path: Path) -> tuple[int, list[QueuedEntrySignal]]:
    target = queue_file_path(config_path)
    if not target.exists():
        return 1, []
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise PropagateError(f"Failed to read entry-signal queue file '{target}': {error}") from error
    if not isinstance(raw, dict):
        raise PropagateError(f"Entry-signal queue file '{target}' must be a mapping.")
    version = raw.get("version")
    if version != QUEUE_VERSION:
        raise PropagateError(f"Entry-signal queue file '{target}' has unsupported version: {version!r}.")
    next_sequence = raw.get("next_sequence", 1)
    if not isinstance(next_sequence, int) or next_sequence < 1:
        raise PropagateError(f"Entry-signal queue file '{target}' has invalid next_sequence.")
    items_raw = raw.get("items", [])
    if not isinstance(items_raw, list):
        raise PropagateError(f"Entry-signal queue file '{target}' has invalid items list.")
    items = [_parse_item(target, item) for item in items_raw]
    return next_sequence, items


def _parse_item(target: Path, item: Any) -> QueuedEntrySignal:
    if not isinstance(item, dict):
        raise PropagateError(f"Entry-signal queue file '{target}' contains a non-mapping item.")
    sequence = item.get("sequence")
    initial_execution = item.get("initial_execution")
    signal_type = item.get("signal_type")
    payload = item.get("payload", {})
    metadata = item.get("metadata", {})
    enqueued_at = item.get("enqueued_at", "")
    if not isinstance(sequence, int) or sequence < 1:
        raise PropagateError(f"Entry-signal queue file '{target}' has an item with invalid sequence.")
    if not isinstance(initial_execution, str) or not initial_execution:
        raise PropagateError(f"Entry-signal queue file '{target}' has an item with invalid initial_execution.")
    if not isinstance(signal_type, str) or not signal_type:
        raise PropagateError(f"Entry-signal queue file '{target}' has an item with invalid signal_type.")
    if not isinstance(payload, dict):
        raise PropagateError(f"Entry-signal queue file '{target}' has an item with invalid payload.")
    if not isinstance(metadata, dict):
        raise PropagateError(f"Entry-signal queue file '{target}' has an item with invalid metadata.")
    if not isinstance(enqueued_at, str):
        raise PropagateError(f"Entry-signal queue file '{target}' has an item with invalid enqueued_at.")
    return QueuedEntrySignal(
        sequence=sequence,
        initial_execution=initial_execution,
        active_signal=ActiveSignal(signal_type=signal_type, payload=payload, source="external"),
        metadata=metadata,
        enqueued_at=enqueued_at,
    )


def _write_queue_document(config_path: Path, next_sequence: int, items: list[QueuedEntrySignal]) -> None:
    target = queue_file_path(config_path)
    data = {
        "version": QUEUE_VERSION,
        "next_sequence": next_sequence,
        "items": [
            {
                "sequence": item.sequence,
                "initial_execution": item.initial_execution,
                "signal_type": item.active_signal.signal_type,
                "payload": item.active_signal.payload,
                "metadata": item.metadata,
                "enqueued_at": item.enqueued_at,
            }
            for item in items
        ],
    }
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.dump(data, handle, default_flow_style=False)
        Path(tmp_path).replace(target)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
