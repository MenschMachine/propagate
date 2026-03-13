from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import PropagateError
from .models import AgentConfig, ContextSourceConfig, RepositoryConfig
from .validation import validate_allowed_keys, validate_context_source_name


def parse_agent(agent_data: Any) -> AgentConfig:
    if not isinstance(agent_data, dict):
        raise PropagateError("Config must include an 'agent' mapping.")
    validate_allowed_keys(agent_data, {"command"}, "Config 'agent'")
    command = agent_data.get("command")
    if not isinstance(command, str) or not command.strip():
        raise PropagateError("Config 'agent.command' must be a non-empty string.")
    if "{prompt_file}" not in command:
        raise PropagateError("Config 'agent.command' must contain the '{prompt_file}' placeholder.")
    return AgentConfig(command=command)


def parse_repositories(repositories_data: Any, config_dir: Path) -> dict[str, RepositoryConfig]:
    if repositories_data is None:
        raise PropagateError("Config is missing required 'repositories' mapping.")
    if not isinstance(repositories_data, dict) or not repositories_data:
        raise PropagateError("Config 'repositories' must be a non-empty mapping.")
    return {
        validate_context_source_name(repository_name): parse_repository(
            validate_context_source_name(repository_name),
            repository_data,
            config_dir,
        )
        for repository_name, repository_data in repositories_data.items()
    }


def parse_repository(repository_name: str, repository_data: Any, config_dir: Path) -> RepositoryConfig:
    if not isinstance(repository_data, dict):
        raise PropagateError(f"Repository '{repository_name}' must be a mapping.")
    validate_allowed_keys(repository_data, {"path", "url", "ref"}, f"Repository '{repository_name}'")
    has_path = "path" in repository_data
    has_url = "url" in repository_data
    if has_path and has_url:
        raise PropagateError(f"Repository '{repository_name}' must declare either 'path' or 'url', not both.")
    if not has_path and not has_url:
        raise PropagateError(f"Repository '{repository_name}' must declare either 'path' or 'url'.")
    ref_value = repository_data.get("ref")
    if ref_value is not None and not has_url:
        raise PropagateError(f"Repository '{repository_name}' declares 'ref' without 'url'.")
    if ref_value is not None and (not isinstance(ref_value, str) or not ref_value.strip()):
        raise PropagateError(f"Repository '{repository_name}' 'ref' must be a non-empty string.")
    if has_url:
        url_value = repository_data.get("url")
        if not isinstance(url_value, str) or not url_value.strip():
            raise PropagateError(f"Repository '{repository_name}' must include a non-empty 'url'.")
        return RepositoryConfig(name=repository_name, path=None, url=url_value, ref=ref_value)
    path_value = repository_data.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        raise PropagateError(f"Repository '{repository_name}' must include a non-empty 'path'.")
    repository_path = Path(path_value).expanduser()
    if not repository_path.is_absolute():
        repository_path = config_dir / repository_path
    return RepositoryConfig(name=repository_name, path=repository_path.resolve())


def parse_context_sources(context_sources_data: Any) -> dict[str, ContextSourceConfig]:
    if context_sources_data is None:
        return {}
    if not isinstance(context_sources_data, dict) or not context_sources_data:
        raise PropagateError("Config 'context_sources' must be a non-empty mapping when provided.")
    return {
        source_name: parse_context_source(source_name, source_data)
        for source_name, source_data in context_sources_data.items()
    }


def parse_context_source(source_name: Any, source_data: Any) -> ContextSourceConfig:
    validated_name = validate_context_source_name(source_name)
    if not isinstance(source_data, dict):
        raise PropagateError(f"Context source '{validated_name}' must be a mapping.")
    validate_allowed_keys(source_data, {"command"}, f"Context source '{validated_name}'")
    command = source_data.get("command")
    if not isinstance(command, str) or not command.strip():
        raise PropagateError(f"Context source '{validated_name}' must include a non-empty 'command'.")
    return ContextSourceConfig(name=validated_name, command=command)
