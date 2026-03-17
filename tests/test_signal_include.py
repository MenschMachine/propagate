import pytest
import yaml

from propagate_app.config_signals import resolve_signal_includes
from propagate_app.errors import PropagateError


@pytest.fixture()
def config_dir(tmp_path):
    includes = tmp_path / "includes"
    includes.mkdir()
    return tmp_path


def write_include(config_dir, filename, data):
    path = config_dir / "includes" / filename
    path.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_no_include_key_returns_data_unchanged(config_dir):
    signals = {"run": {"payload": {}}}
    result = resolve_signal_includes(signals, config_dir)
    assert result == {"run": {"payload": {}}}


def test_single_include_file(config_dir):
    write_include(config_dir, "gh.yaml", {
        "pr.labeled": {"payload": {"label": {"type": "string", "required": True}}},
    })
    signals = {
        "include": "includes/gh.yaml",
        "run": {"payload": {}},
    }
    result = resolve_signal_includes(signals, config_dir)
    assert "run" in result
    assert "pr.labeled" in result
    assert "include" not in result


def test_multiple_include_files(config_dir):
    write_include(config_dir, "gh.yaml", {
        "pr.labeled": {"payload": {"label": {"type": "string"}}},
    })
    write_include(config_dir, "deploy.yaml", {
        "deploy": {"payload": {"branch": {"type": "string"}}},
    })
    signals = {
        "include": ["includes/gh.yaml", "includes/deploy.yaml"],
        "run": {"payload": {}},
    }
    result = resolve_signal_includes(signals, config_dir)
    assert "run" in result
    assert "pr.labeled" in result
    assert "deploy" in result


def test_inline_overrides_included_signal(config_dir):
    write_include(config_dir, "gh.yaml", {
        "run": {"payload": {"branch": {"type": "string"}}},
    })
    signals = {
        "include": "includes/gh.yaml",
        "run": {"payload": {}},
    }
    result = resolve_signal_includes(signals, config_dir)
    # Inline definition wins — payload should be the empty one from inline
    assert result["run"] == {"payload": {}}


def test_inline_override_preserves_inline_payload(config_dir):
    write_include(config_dir, "shared.yaml", {
        "start": {"payload": {"env": {"type": "string"}}},
    })
    signals = {
        "include": "includes/shared.yaml",
        "start": {"payload": {"url": {"type": "string", "required": True}}},
    }
    result = resolve_signal_includes(signals, config_dir)
    assert result["start"] == {"payload": {"url": {"type": "string", "required": True}}}


def test_duplicate_between_two_includes_raises(config_dir):
    write_include(config_dir, "a.yaml", {
        "deploy": {"payload": {}},
    })
    write_include(config_dir, "b.yaml", {
        "deploy": {"payload": {}},
    })
    signals = {
        "include": ["includes/a.yaml", "includes/b.yaml"],
    }
    with pytest.raises(PropagateError, match="Duplicate signal 'deploy'"):
        resolve_signal_includes(signals, config_dir)


def test_missing_include_file_raises(config_dir):
    signals = {"include": "includes/nonexistent.yaml"}
    with pytest.raises(PropagateError, match="does not exist"):
        resolve_signal_includes(signals, config_dir)


def test_include_file_not_a_mapping_raises(config_dir):
    path = config_dir / "includes" / "bad.yaml"
    path.write_text("- item1\n- item2\n", encoding="utf-8")
    signals = {"include": "includes/bad.yaml"}
    with pytest.raises(PropagateError, match="must be a YAML mapping"):
        resolve_signal_includes(signals, config_dir)


def test_include_invalid_yaml_raises(config_dir):
    path = config_dir / "includes" / "bad.yaml"
    path.write_text(": :\n  : :\n[broken", encoding="utf-8")
    signals = {"include": "includes/bad.yaml"}
    with pytest.raises(PropagateError, match="Failed to parse"):
        resolve_signal_includes(signals, config_dir)


def test_include_invalid_type_raises(config_dir):
    signals = {"include": 42}
    with pytest.raises(PropagateError, match="must be a string or list of strings"):
        resolve_signal_includes(signals, config_dir)


def test_included_signals_pass_through_normal_validation(config_dir):
    """Included signals go through parse_signal_configs which validates payload structure."""
    from propagate_app.config_signals import parse_signal_configs

    write_include(config_dir, "gh.yaml", {
        "pr.labeled": {"payload": {"label": {"type": "string", "required": True}}},
    })
    signals = {
        "include": "includes/gh.yaml",
        "run": {"payload": {}},
    }
    resolved = resolve_signal_includes(signals, config_dir)
    parsed = parse_signal_configs(resolved)
    assert "pr.labeled" in parsed
    assert "run" in parsed
    assert parsed["pr.labeled"].payload["label"].required is True
