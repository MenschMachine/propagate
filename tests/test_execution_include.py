import pytest
import yaml

from propagate_app.config_executions import resolve_execution_includes
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


def _minimal_execution(repo="my-repo"):
    return {
        "repository": repo,
        "sub_tasks": [{"id": "do-stuff", "prompt": "./prompts/do.md"}],
    }


def test_no_include_key_returns_data_unchanged(config_dir):
    executions = {"build": _minimal_execution()}
    result = resolve_execution_includes(executions, config_dir)
    assert result == {"build": _minimal_execution()}


def test_single_include_file(config_dir):
    write_include(config_dir, "deploy.yaml", {
        "deploy": _minimal_execution(),
    })
    executions = {
        "include": "signals/deploy.yaml",
        "build": _minimal_execution(),
    }
    result = resolve_execution_includes(executions, config_dir)
    assert "build" in result
    assert "deploy" in result
    assert "include" not in result


def test_multiple_include_files(config_dir):
    write_include(config_dir, "deploy.yaml", {
        "deploy": _minimal_execution(),
    })
    write_include(config_dir, "test.yaml", {
        "test": _minimal_execution(),
    })
    executions = {
        "include": ["signals/deploy.yaml", "signals/test.yaml"],
        "build": _minimal_execution(),
    }
    result = resolve_execution_includes(executions, config_dir)
    assert "build" in result
    assert "deploy" in result
    assert "test" in result


def test_inline_overrides_included_execution(config_dir):
    write_include(config_dir, "shared.yaml", {
        "build": _minimal_execution("other-repo"),
    })
    executions = {
        "include": "signals/shared.yaml",
        "build": _minimal_execution("my-repo"),
    }
    result = resolve_execution_includes(executions, config_dir)
    assert result["build"]["repository"] == "my-repo"


def test_inline_override_preserves_inline_data(config_dir):
    write_include(config_dir, "shared.yaml", {
        "build": _minimal_execution("included-repo"),
    })
    inline_exec = _minimal_execution("inline-repo")
    inline_exec["sub_tasks"].append({"id": "extra", "prompt": "./prompts/extra.md"})
    executions = {
        "include": "signals/shared.yaml",
        "build": inline_exec,
    }
    result = resolve_execution_includes(executions, config_dir)
    assert result["build"]["repository"] == "inline-repo"
    assert len(result["build"]["sub_tasks"]) == 2


def test_duplicate_between_two_includes_raises(config_dir):
    write_include(config_dir, "a.yaml", {
        "deploy": _minimal_execution(),
    })
    write_include(config_dir, "b.yaml", {
        "deploy": _minimal_execution(),
    })
    executions = {
        "include": ["signals/a.yaml", "signals/b.yaml"],
    }
    with pytest.raises(PropagateError, match="Duplicate execution 'deploy'"):
        resolve_execution_includes(executions, config_dir)


def test_missing_include_file_raises(config_dir):
    executions = {"include": "signals/nonexistent.yaml"}
    with pytest.raises(PropagateError, match="does not exist"):
        resolve_execution_includes(executions, config_dir)


def test_include_file_not_a_mapping_raises(config_dir):
    path = config_dir / "signals" / "bad.yaml"
    path.write_text("- item1\n- item2\n", encoding="utf-8")
    executions = {"include": "signals/bad.yaml"}
    with pytest.raises(PropagateError, match="must be a YAML mapping"):
        resolve_execution_includes(executions, config_dir)


def test_include_invalid_yaml_raises(config_dir):
    path = config_dir / "signals" / "bad.yaml"
    path.write_text(": :\n  : :\n[broken", encoding="utf-8")
    executions = {"include": "signals/bad.yaml"}
    with pytest.raises(PropagateError, match="Failed to parse"):
        resolve_execution_includes(executions, config_dir)


def test_include_invalid_type_raises(config_dir):
    executions = {"include": 42}
    with pytest.raises(PropagateError, match="must be a string or list of strings"):
        resolve_execution_includes(executions, config_dir)


def test_empty_include_list_returns_empty(config_dir):
    executions = {"include": []}
    result = resolve_execution_includes(executions, config_dir)
    assert result == {}


def test_included_executions_pass_through_normal_validation(config_dir):
    """Included executions go through parse_executions which validates structure."""
    from propagate_app.config_executions import parse_executions

    write_include(config_dir, "deploy.yaml", {
        "deploy": {
            "repository": "my-repo",
            "sub_tasks": [{"id": "run", "prompt": "./prompts/run.md"}],
        },
    })
    executions = {
        "include": "signals/deploy.yaml",
        "build": {
            "repository": "my-repo",
            "sub_tasks": [{"id": "compile", "prompt": "./prompts/compile.md"}],
        },
    }
    resolved = resolve_execution_includes(executions, config_dir)
    parsed = parse_executions(
        resolved,
        config_dir,
        repository_names={"my-repo"},
        context_source_names=set(),
        signal_configs={},
    )
    assert "deploy" in parsed
    assert "build" in parsed
    assert parsed["deploy"].sub_tasks[0].task_id == "run"
