from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from re import Pattern
from typing import Any

import yaml

from .constants import LOGGER
from .errors import PropagateError
from .validation import validate_allowed_keys, validate_context_source_name

_PLACEHOLDER_PATTERN: Pattern[str] = re.compile(r"{{\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*}}")
_FULL_PLACEHOLDER_PATTERN: Pattern[str] = re.compile(r"^\s*{{\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*}}\s*$")
_FULL_PLACEHOLDER_WITH_DEFAULT_PATTERN: Pattern[str] = re.compile(r"^\s*{{\s*([A-Za-z0-9][A-Za-z0-9._-]*)\|([^}]+)}}\s*$")
_ScalarParameter = str | int | float | bool
_ParameterValue = _ScalarParameter | list[str] | None


@dataclass(frozen=True)
class IncludeSpec:
    path: str
    parameters: dict[str, _ParameterValue]


def resolve_mapping_includes(
    data: dict[str, Any],
    config_dir: Path,
    *,
    section_name: str,
    entry_name: str,
    allow_placeholder_keys: bool = False,
) -> dict[str, Any]:
    """Pop 'include', load referenced files, render parameters, and merge with inline mappings."""
    inline = dict(data)
    include_data = inline.pop("include", None)
    if include_data is None:
        return inline
    include_specs = parse_include_specs(include_data, section_name)
    all_included: dict[str, Any] = {}
    for include_spec in include_specs:
        file_path = (config_dir / include_spec.path).resolve()
        if not file_path.exists():
            raise PropagateError(f"{entry_name.capitalize()} include file does not exist: {file_path}")
        LOGGER.debug("Loading %s include: %s", entry_name, file_path)
        try:
            with file_path.open("r", encoding="utf-8") as handle:
                included = yaml.safe_load(handle)
        except yaml.YAMLError as error:
            raise PropagateError(
                f"Failed to parse {entry_name} include file {file_path}: {error}"
            ) from error
        if not isinstance(included, dict):
            raise PropagateError(
                f"{entry_name.capitalize()} include file must be a YAML mapping: {file_path}"
            )
        rendered = render_included_mapping(
            included,
            include_spec.parameters,
            file_path,
            allow_placeholder_keys=allow_placeholder_keys,
        )
        for key in rendered:
            if key in all_included:
                raise PropagateError(
                    f"Duplicate {entry_name} '{key}' from include file {file_path}"
                )
        all_included.update(rendered)
    for key in inline:
        if key in all_included:
            LOGGER.debug("Inline %s '%s' overrides included definition", entry_name, key)
    return {**all_included, **inline}


def parse_include_specs(include_data: Any, section_name: str) -> list[IncludeSpec]:
    if isinstance(include_data, (str, dict)):
        raw_items = [include_data]
    elif isinstance(include_data, list):
        raw_items = include_data
    else:
        raise PropagateError(
            f"{section_name}.include must be a string, a mapping, or a list containing strings and mappings."
        )
    include_specs: list[IncludeSpec] = []
    for index, raw_item in enumerate(raw_items, start=1):
        location = f"{section_name}.include item #{index}"
        include_specs.append(parse_include_spec(raw_item, location))
    return include_specs


def parse_include_spec(raw_item: Any, location: str) -> IncludeSpec:
    if isinstance(raw_item, str):
        if not raw_item.strip():
            raise PropagateError(f"{location} must be a non-empty string when provided as a path.")
        return IncludeSpec(path=raw_item, parameters={})
    if not isinstance(raw_item, dict):
        raise PropagateError(f"{location} must be either a path string or a mapping.")
    validate_allowed_keys(raw_item, {"path", "with"}, location)
    path = raw_item.get("path")
    if not isinstance(path, str) or not path.strip():
        raise PropagateError(f"{location}.path must be a non-empty string.")
    parameters_data = raw_item.get("with", {})
    if not isinstance(parameters_data, dict):
        raise PropagateError(f"{location}.with must be a mapping when provided.")
    parameters: dict[str, _ParameterValue] = {}
    for key, value in parameters_data.items():
        parameter_name = validate_context_source_name(key)
        if value is None or isinstance(value, bool) or isinstance(value, (str, int, float)):
            parameters[parameter_name] = value
        elif isinstance(value, list) and all(isinstance(item, str) and item for item in value):
            parameters[parameter_name] = value
        else:
            raise PropagateError(
                f"{location}.with['{parameter_name}'] must be null, a string, number, boolean, or list of non-empty strings."
            )
    return IncludeSpec(path=path, parameters=parameters)


def render_included_mapping(
    data: dict[str, Any],
    parameters: dict[str, _ParameterValue],
    source_path: Path,
    *,
    allow_placeholder_keys: bool = False,
) -> dict[str, Any]:
    used_parameters: set[str] = set()
    rendered: dict[str, Any] = {}
    for key, value in data.items():
        rendered_key = key
        if isinstance(key, str) and ("{{" in key or "}}" in key):
            if not allow_placeholder_keys:
                raise PropagateError(f"Include file {source_path} must not use template placeholders in mapping keys.")
            rendered_key = render_included_value(key, parameters, used_parameters, source_path)
            if not isinstance(rendered_key, str) or not rendered_key:
                raise PropagateError(f"Include file {source_path} rendered an invalid mapping key.")
            rendered_key = validate_context_source_name(rendered_key)
        rendered[rendered_key] = render_included_value(value, parameters, used_parameters, source_path)
    unused_parameters = sorted(set(parameters) - used_parameters)
    if unused_parameters:
        raise PropagateError(
            f"Include file {source_path} received unused template parameters: {', '.join(unused_parameters)}."
        )
    return rendered


def render_included_value(
    value: Any,
    parameters: dict[str, _ParameterValue],
    used_parameters: set[str],
    source_path: Path,
) -> Any:
    if isinstance(value, dict):
        rendered: dict[str, Any] = {}
        for key, inner_value in value.items():
            if isinstance(key, str) and ("{{" in key or "}}" in key):
                raise PropagateError(f"Include file {source_path} must not use template placeholders in mapping keys.")
            rendered[key] = render_included_value(inner_value, parameters, used_parameters, source_path)
        return rendered
    if isinstance(value, list):
        return [render_included_value(item, parameters, used_parameters, source_path) for item in value]
    if not isinstance(value, str):
        return value
    _validate_template_syntax(value, source_path)
    full_match = _FULL_PLACEHOLDER_PATTERN.fullmatch(value)
    if full_match is not None:
        parameter_name = full_match.group(1)
        if parameter_name not in parameters:
            raise PropagateError(f"Include file {source_path} references unknown template parameter '{parameter_name}'.")
        used_parameters.add(parameter_name)
        return parameters[parameter_name]
    with_default_match = _FULL_PLACEHOLDER_WITH_DEFAULT_PATTERN.fullmatch(value)
    if with_default_match is not None:
        parameter_name = with_default_match.group(1)
        default_value = with_default_match.group(2).strip()
        if default_value.startswith(("'", '"')) and default_value.endswith(("'", '"')) and len(default_value) >= 2:
            default_value = default_value[1:-1]
        used_parameters.add(parameter_name)
        if parameter_name in parameters:
            return parameters[parameter_name]
        return default_value

    def replace_placeholder(match: re.Match[str]) -> str:
        parameter_name = match.group(1)
        if parameter_name not in parameters:
            raise PropagateError(f"Include file {source_path} references unknown template parameter '{parameter_name}'.")
        used_parameters.add(parameter_name)
        parameter_value = parameters[parameter_name]
        if not isinstance(parameter_value, (str, int, float, bool)):
            raise PropagateError(
                f"Include file {source_path} references non-scalar template parameter '{parameter_name}' inside a larger string."
            )
        return str(parameter_value)

    return _PLACEHOLDER_PATTERN.sub(replace_placeholder, value)


def _validate_template_syntax(value: str, source_path: Path) -> None:
    index = 0
    while True:
        start = value.find("{{", index)
        if start == -1:
            return
        cursor = start + 2
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        if cursor >= len(value):
            raise PropagateError(f"Include file {source_path} contains invalid template placeholder syntax.")
        if not value[cursor].isalnum():
            index = start + 2
            continue
        end = value.find("}}", cursor)
        if end == -1:
            raise PropagateError(f"Include file {source_path} contains invalid template placeholder syntax.")
        candidate = value[start:end + 2]
        if _PLACEHOLDER_PATTERN.fullmatch(candidate) is None and _FULL_PLACEHOLDER_WITH_DEFAULT_PATTERN.fullmatch(candidate) is None:
            raise PropagateError(f"Include file {source_path} contains invalid template placeholder syntax.")
        index = end + 2
