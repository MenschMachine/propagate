import pytest
import yaml

from propagate_app.config_signals import resolve_signal_includes
from propagate_app.errors import PropagateError


@pytest.fixture()
def config_dir(tmp_path):
    includes = tmp_path / "signals"
    includes.mkdir()
    return tmp_path


def write_include(config_dir, filename, data):
    path = config_dir / "signals" / filename
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
        "include": "signals/gh.yaml",
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
        "include": ["signals/gh.yaml", "signals/deploy.yaml"],
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
        "include": "signals/gh.yaml",
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
        "include": "signals/shared.yaml",
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
        "include": ["signals/a.yaml", "signals/b.yaml"],
    }
    with pytest.raises(PropagateError, match="Duplicate signal 'deploy'"):
        resolve_signal_includes(signals, config_dir)


def test_missing_include_file_raises(config_dir):
    signals = {"include": "signals/nonexistent.yaml"}
    with pytest.raises(PropagateError, match="does not exist"):
        resolve_signal_includes(signals, config_dir)


def test_include_file_not_a_mapping_raises(config_dir):
    path = config_dir / "signals" / "bad.yaml"
    path.write_text("- item1\n- item2\n", encoding="utf-8")
    signals = {"include": "signals/bad.yaml"}
    with pytest.raises(PropagateError, match="must be a YAML mapping"):
        resolve_signal_includes(signals, config_dir)


def test_include_invalid_yaml_raises(config_dir):
    path = config_dir / "signals" / "bad.yaml"
    path.write_text(": :\n  : :\n[broken", encoding="utf-8")
    signals = {"include": "signals/bad.yaml"}
    with pytest.raises(PropagateError, match="Failed to parse"):
        resolve_signal_includes(signals, config_dir)


def test_include_invalid_type_raises(config_dir):
    signals = {"include": 42}
    with pytest.raises(PropagateError, match="must be a string, a mapping, or a list"):
        resolve_signal_includes(signals, config_dir)


def test_included_signals_pass_through_normal_validation(config_dir):
    """Included signals go through parse_signal_configs which validates payload structure."""
    from propagate_app.config_signals import parse_signal_configs

    write_include(config_dir, "gh.yaml", {
        "pr.labeled": {"payload": {"label": {"type": "string", "required": True}}},
    })
    signals = {
        "include": "signals/gh.yaml",
        "run": {"payload": {}},
    }
    resolved = resolve_signal_includes(signals, config_dir)
    parsed = parse_signal_configs(resolved)
    assert "pr.labeled" in parsed
    assert "run" in parsed
    assert parsed["pr.labeled"].payload["label"].required is True


def test_parameterized_include_renders_signal_fields_and_preserves_scalar_types(config_dir):
    from propagate_app.config_signals import parse_signal_configs

    write_include(config_dir, "templated.yaml", {
        "pr.labeled": {
            "payload": {
                "label": {"type": "{{ label_type }}", "required": "{{ label_required }}"},
            },
            "check": "gh pr view {pr_number} --repo {{ repository }}",
        },
    })
    signals = {
        "include": [{
            "path": "signals/templated.yaml",
            "with": {
                "label_type": "string",
                "label_required": True,
                "repository": "myorg/myrepo",
            },
        }],
    }
    resolved = resolve_signal_includes(signals, config_dir)
    assert resolved["pr.labeled"]["payload"]["label"]["required"] is True
    assert resolved["pr.labeled"]["check"] == "gh pr view {pr_number} --repo myorg/myrepo"

    parsed = parse_signal_configs(resolved)
    assert parsed["pr.labeled"].payload["label"].required is True


def test_parameterized_include_rejects_placeholders_in_keys(config_dir):
    write_include(config_dir, "templated.yaml", {
        "{{ signal_name }}": {"payload": {}},
    })
    signals = {
        "include": [{
            "path": "signals/templated.yaml",
            "with": {"signal_name": "run"},
        }],
    }
    with pytest.raises(PropagateError, match="must not use template placeholders in mapping keys"):
        resolve_signal_includes(signals, config_dir)


def test_parameterized_include_rejects_unused_parameter(config_dir):
    write_include(config_dir, "templated.yaml", {
        "run": {"payload": {}},
    })
    signals = {
        "include": [{
            "path": "signals/templated.yaml",
            "with": {"unused_param": "extra"},
        }],
    }
    with pytest.raises(PropagateError, match="unused template parameters: unused_param"):
        resolve_signal_includes(signals, config_dir)


def test_parameterized_include_preserves_literal_non_placeholder_mustache_text(config_dir):
    write_include(config_dir, "templated.yaml", {
        "run": {
            "payload": {},
            "check": "printf '{{.status}} {{ repository }}'",
        },
    })
    signals = {
        "include": [{
            "path": "signals/templated.yaml",
            "with": {"repository": "myorg/myrepo"},
        }],
    }
    resolved = resolve_signal_includes(signals, config_dir)
    assert resolved["run"]["check"] == "printf '{{.status}} myorg/myrepo'"


@pytest.mark.parametrize(
    "bad_value",
    [
        "{{ repository }",
        "{{ repository",
        "prefix {{ repository } suffix",
        "{{ repository !}}",
    ],
)
def test_parameterized_include_rejects_malformed_placeholder_syntax(config_dir, bad_value):
    write_include(config_dir, "templated.yaml", {
        "run": {
            "payload": {},
            "check": bad_value,
        },
    })
    signals = {
        "include": [{
            "path": "signals/templated.yaml",
            "with": {"repository": "myorg/myrepo"},
        }],
    }
    with pytest.raises(PropagateError, match="invalid template placeholder syntax"):
        resolve_signal_includes(signals, config_dir)
