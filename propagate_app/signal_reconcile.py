from __future__ import annotations

import shlex
import subprocess
from string import Formatter

from .constants import LOGGER
from .context_store import get_context_root, get_execution_context_dir
from .models import ActiveSignal, Config, ExecutionGraph, ExecutionScheduleState
from .signals import resolve_signal_when_payload


def reconcile_pending_signals(
    config: Config,
    execution_graph: ExecutionGraph,
    schedule_state: ExecutionScheduleState,
    received_signal_types: set[str],
    reconciled_triggers: set[tuple[str, str, str]] | None = None,
) -> bool:
    """Check pending signal triggers whose condition may already be met.

    For each pending trigger with on_signal + when, if the signal definition has
    a check command, run it templated with the when values.  If it exits 0, the
    condition is already satisfied — synthesize a signal and activate triggers.

    ``reconciled_triggers`` tracks (after, run, on_signal) tuples whose check
    already passed, so they are not re-checked.  Triggers whose check failed
    are retried on subsequent calls.

    Returns True if any trigger was reconciled.
    """
    from .scheduler import activate_matching_triggers

    if reconciled_triggers is None:
        reconciled_triggers = set()
    reconciled = False
    for completed_name in list(schedule_state.completed_names):
        for trigger in execution_graph.triggers_by_after[completed_name]:
            if trigger.on_signal is None or trigger.when is None:
                continue
            if trigger.run in schedule_state.completed_names or trigger.run in schedule_state.active_names:
                continue
            trigger_key = (trigger.after, trigger.run, trigger.on_signal)
            if trigger_key in reconciled_triggers:
                continue
            signal_config = config.signals.get(trigger.on_signal)
            if signal_config is None or signal_config.check is None:
                continue
            context_dir = get_execution_context_dir(get_context_root(config.config_path), completed_name)
            resolved_when = resolve_signal_when_payload(trigger.when, signal_config, context_dir)
            if resolved_when is None:
                continue
            if not _template_has_valid_keys(signal_config.check, resolved_when):
                continue
            if _run_signal_check(signal_config.check, resolved_when):
                LOGGER.debug(
                    "Signal check passed for '%s' (trigger after '%s' run '%s'); reconciling.",
                    trigger.on_signal, trigger.after, trigger.run,
                )
                reconciled_triggers.add(trigger_key)
                active_signal = ActiveSignal(
                    signal_type=trigger.on_signal,
                    payload=resolved_when,
                    source="reconciled",
                )
                received_signal_types.add(trigger.on_signal)
                activate_matching_triggers(
                    config,
                    execution_graph,
                    completed_name,
                    active_signal,
                    schedule_state.active_names,
                    schedule_state.completed_names,
                )
                reconciled = True
    return reconciled


def _template_has_valid_keys(command_template: str, when_values: dict) -> bool:
    """Return True if all placeholders in command_template exist in when_values."""
    formatter = Formatter()
    for _, field_name, _, _ in formatter.parse(command_template):
        if field_name is not None and field_name not in when_values:
            LOGGER.debug(
                "Check command placeholder '{%s}' not found in when values; skipping.",
                field_name,
            )
            return False
    return True


def _run_signal_check(command_template: str, when_values: dict) -> bool:
    """Template when values into the check command and run it.

    Returns True if the command exits 0 (condition already met).
    """
    quoted_values = {k: shlex.quote(str(v)) for k, v in when_values.items()}
    command = command_template.format_map(quoted_values)
    LOGGER.debug("Running signal check command: %s", command)
    try:
        result = subprocess.run(command, shell=True, check=False, capture_output=True, timeout=30)  # noqa: S602
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        LOGGER.debug("Signal check command timed out: %s", command)
        return False
    except OSError:
        LOGGER.debug("Signal check command failed with OSError: %s", command)
        return False
