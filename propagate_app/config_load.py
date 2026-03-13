from __future__ import annotations

from pathlib import Path

import yaml

from .config_agent import parse_agent, parse_context_sources, parse_repositories
from .config_executions import parse_executions
from .config_signals import parse_signal_configs
from .errors import PropagateError
from .graph import parse_propagation_triggers, validate_execution_graph_is_acyclic
from .models import Config
from .repo_clone import clone_url_repositories
from .validation import validate_allowed_keys


def load_config(config_path: Path, existing_clones: dict[str, Path] | None = None) -> Config:
    if not config_path.exists():
        raise PropagateError(f"Config file does not exist: {config_path}")
    resolved_config_path = config_path.resolve()
    try:
        with resolved_config_path.open("r", encoding="utf-8") as handle:
            raw_data = yaml.safe_load(handle)
    except OSError as error:
        raise PropagateError(f"Failed to read config file {resolved_config_path}: {error}") from error
    except yaml.YAMLError as error:
        raise PropagateError(f"Failed to parse YAML config {resolved_config_path}: {error}") from error
    if not isinstance(raw_data, dict):
        raise PropagateError("Config must be a YAML mapping.")
    validate_allowed_keys(
        raw_data,
        {"version", "agent", "repositories", "context_sources", "signals", "executions", "propagation"},
        "Config",
    )
    version = raw_data.get("version")
    if version != "6":
        raise PropagateError("Config version must be '6' for stage 6.")
    agent = parse_agent(raw_data.get("agent"))
    repositories = parse_repositories(raw_data.get("repositories"), resolved_config_path.parent)
    context_sources = parse_context_sources(raw_data.get("context_sources"))
    signals = parse_signal_configs(raw_data.get("signals"))
    executions = parse_executions(
        raw_data.get("executions"),
        resolved_config_path.parent,
        set(repositories),
        set(context_sources),
        set(signals),
    )
    propagation_triggers = parse_propagation_triggers(raw_data.get("propagation"), set(executions), set(signals))
    validate_execution_graph_is_acyclic(executions, propagation_triggers)
    config = Config(
        version=version,
        agent=agent,
        repositories=repositories,
        context_sources=context_sources,
        signals=signals,
        propagation_triggers=propagation_triggers,
        executions=executions,
        config_path=resolved_config_path,
    )
    return clone_url_repositories(config, existing_clones=existing_clones)
