from __future__ import annotations

from pathlib import Path

import yaml

from .config_agent import parse_agent, parse_context_sources, parse_repositories
from .config_executions import parse_executions, resolve_execution_includes
from .config_signals import parse_signal_configs, resolve_signal_includes
from .errors import PropagateError
from .graph import parse_propagation_triggers, validate_execution_graph_is_acyclic
from .models import Config
from .validation import validate_allowed_keys


def load_config(config_path: Path) -> Config:
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
        {"version", "agent", "agents", "repositories", "context_sources", "signals", "executions", "propagation", "clone_dir", "repo_cache_dir"},
        "Config",
    )
    version = raw_data.get("version")
    if version != "6":
        raise PropagateError("Config version must be '6' for stage 6.")
    agent = parse_agent(raw_data.get("agent"), raw_data.get("agents"))
    repositories = parse_repositories(raw_data.get("repositories"), resolved_config_path.parent)
    context_sources = parse_context_sources(raw_data.get("context_sources"))
    raw_signals = raw_data.get("signals")
    if isinstance(raw_signals, dict) and "include" in raw_signals:
        raw_signals = resolve_signal_includes(raw_signals, resolved_config_path.parent)
    signals = parse_signal_configs(raw_signals)
    raw_executions = raw_data.get("executions")
    if isinstance(raw_executions, dict) and "include" in raw_executions:
        raw_executions = resolve_execution_includes(raw_executions, resolved_config_path.parent)
    executions = parse_executions(
        raw_executions,
        resolved_config_path.parent,
        set(repositories),
        set(context_sources),
        signals,
    )
    propagation_triggers = parse_propagation_triggers(raw_data.get("propagation"), set(executions), signals)
    validate_execution_graph_is_acyclic(executions, propagation_triggers)
    raw_clone_dir = raw_data.get("clone_dir")
    clone_dir = None
    if raw_clone_dir is not None:
        clone_dir = Path(raw_clone_dir)
        if not clone_dir.is_absolute():
            clone_dir = (resolved_config_path.parent / clone_dir).resolve()
    raw_repo_cache_dir = raw_data.get("repo_cache_dir", ".repo-cache")
    repo_cache_dir = Path(raw_repo_cache_dir)
    if not repo_cache_dir.is_absolute():
        repo_cache_dir = (resolved_config_path.parent / repo_cache_dir).resolve()
    config = Config(
        version=version,
        agent=agent,
        repositories=repositories,
        context_sources=context_sources,
        signals=signals,
        propagation_triggers=propagation_triggers,
        executions=executions,
        config_path=resolved_config_path,
        clone_dir=clone_dir,
        repo_cache_dir=repo_cache_dir,
    )
    return config
