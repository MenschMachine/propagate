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
    with pytest.raises(PropagateError, match="must be a string, a mapping, or a list"):
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
        agent_names=set(),
    )
    assert "deploy" in parsed
    assert "build" in parsed
    assert parsed["deploy"].sub_tasks[0].task_id == "run"


def test_parameterized_include_renders_execution_fields(config_dir):
    write_include(config_dir, "review.yaml", {
        "review-loop": {
            "repository": "{{ repository }}",
            "sub_tasks": [
                {"id": "implement", "prompt": "{{ implement_prompt }}"},
                {"id": "summarize", "prompt": "{{ summarize_prompt }}"},
                {
                    "id": "wait",
                    "wait_for_signal": "pull_request.labeled",
                    "routes": [
                        {"when": {"label": "{{ retry_label }}"}, "goto": "implement"},
                        {"when": {"label": "{{ approve_label }}"}, "continue": True},
                    ],
                },
            ],
        },
    })
    executions = {
        "include": [{
            "path": "signals/review.yaml",
            "with": {
                "repository": "my-repo",
                "implement_prompt": "./prompts/implement.md",
                "summarize_prompt": "./prompts/summarize.md",
                "retry_label": "changes_required",
                "approve_label": "approved",
            },
        }],
    }
    result = resolve_execution_includes(executions, config_dir)
    review_loop = result["review-loop"]
    assert review_loop["repository"] == "my-repo"
    assert review_loop["sub_tasks"][0]["prompt"] == "./prompts/implement.md"
    assert review_loop["sub_tasks"][2]["routes"][0]["when"]["label"] == "changes_required"
    assert review_loop["sub_tasks"][2]["routes"][1]["when"]["label"] == "approved"


def test_parameterized_include_can_render_top_level_execution_name(config_dir):
    write_include(config_dir, "review.yaml", {
        "{{ execution_name }}": {
            "repository": "{{ repository }}",
            "sub_tasks": [{"id": "implement", "prompt": "{{ implement_prompt }}"}],
        },
    })
    executions = {
        "include": [{
            "path": "signals/review.yaml",
            "with": {
                "execution_name": "sdk-review",
                "repository": "my-repo",
                "implement_prompt": "./prompts/implement.md",
            },
        }],
    }
    result = resolve_execution_includes(executions, config_dir)
    assert "sdk-review" in result
    assert result["sdk-review"]["repository"] == "my-repo"


def test_parameterized_include_rejects_invalid_top_level_execution_name(config_dir):
    write_include(config_dir, "review.yaml", {
        "{{ execution_name }}": {
            "repository": "{{ repository }}",
            "sub_tasks": [{"id": "implement", "prompt": "{{ implement_prompt }}"}],
        },
    })
    executions = {
        "include": [{
            "path": "signals/review.yaml",
            "with": {
                "execution_name": "bad name",
                "repository": "my-repo",
                "implement_prompt": "./prompts/implement.md",
            },
        }],
    }
    with pytest.raises(PropagateError, match="Invalid context source name 'bad name'"):
        resolve_execution_includes(executions, config_dir)


def test_parameterized_include_prompt_path_still_resolves_from_root_config_dir(config_dir):
    from propagate_app.config_executions import parse_executions

    shared_dir = config_dir / "shared"
    shared_dir.mkdir()
    include_path = shared_dir / "review.yaml"
    include_path.write_text(yaml.dump({
        "review-loop": {
            "repository": "{{ repository }}",
            "sub_tasks": [{"id": "implement", "prompt": "{{ implement_prompt }}"}],
        },
    }, sort_keys=False), encoding="utf-8")

    prompts_dir = config_dir / "project-prompts"
    prompts_dir.mkdir()
    prompt_path = prompts_dir / "implement.md"
    prompt_path.write_text("Implement.\n", encoding="utf-8")

    executions = {
        "include": [{
            "path": "shared/review.yaml",
            "with": {
                "repository": "my-repo",
                "implement_prompt": "./project-prompts/implement.md",
            },
        }],
    }
    resolved = resolve_execution_includes(executions, config_dir)
    parsed = parse_executions(
        resolved,
        config_dir,
        repository_names={"my-repo"},
        context_source_names=set(),
        signal_configs={},
        agent_names=set(),
    )
    assert parsed["review-loop"].sub_tasks[0].prompt_path == prompt_path.resolve()


def test_parameterized_include_missing_parameter_raises(config_dir):
    write_include(config_dir, "review.yaml", {
        "review-loop": {
            "repository": "{{ repository }}",
            "sub_tasks": [{"id": "implement", "prompt": "{{ implement_prompt }}"}],
        },
    })
    executions = {
        "include": [{
            "path": "signals/review.yaml",
            "with": {"repository": "my-repo"},
        }],
    }
    with pytest.raises(PropagateError, match="unknown template parameter 'implement_prompt'"):
        resolve_execution_includes(executions, config_dir)


def test_parameterized_include_unused_parameter_raises(config_dir):
    write_include(config_dir, "review.yaml", {
        "review-loop": {
            "repository": "{{ repository }}",
            "sub_tasks": [{"id": "implement", "prompt": "./prompts/implement.md"}],
        },
    })
    executions = {
        "include": [{
            "path": "signals/review.yaml",
            "with": {
                "repository": "my-repo",
                "unused_value": "extra",
            },
        }],
    }
    with pytest.raises(PropagateError, match="unused template parameters: unused_value"):
        resolve_execution_includes(executions, config_dir)


def test_parameterized_include_with_default_value_used_when_param_absent(config_dir):
    write_include(config_dir, "review.yaml", {
        "review-loop": {
            "repository": "{{ repository }}",
            "agent": "{{ agent| }}",
            "sub_tasks": [{"id": "implement", "prompt": "{{ implement_prompt }}"}],
        },
    })
    executions = {
        "include": [{
            "path": "signals/review.yaml",
            "with": {
                "repository": "my-repo",
                "implement_prompt": "./prompts/implement.md",
                # agent not passed — should use default
            },
        }],
    }
    resolved = resolve_execution_includes(executions, config_dir)
    # Empty default renders as empty string — parse_execution_agent treats this as None
    assert resolved["review-loop"]["agent"] == ""
    assert resolved["review-loop"]["repository"] == "my-repo"


def test_parameterized_include_with_default_value_overridden_when_param_provided(config_dir):
    write_include(config_dir, "review.yaml", {
        "review-loop": {
            "repository": "{{ repository }}",
            "agent": "{{ agent| }}",
            "sub_tasks": [{"id": "implement", "prompt": "{{ implement_prompt }}"}],
        },
    })
    executions = {
        "include": [{
            "path": "signals/review.yaml",
            "with": {
                "repository": "my-repo",
                "agent": "custom-agent",
                "implement_prompt": "./prompts/implement.md",
            },
        }],
    }
    resolved = resolve_execution_includes(executions, config_dir)
    assert resolved["review-loop"]["agent"] == "custom-agent"


def test_parameterized_include_default_value_not_flagged_as_unused(config_dir):
    """A param with a default that isn't passed should not cause 'unused param' error."""
    write_include(config_dir, "review.yaml", {
        "review-loop": {
            "repository": "{{ repository }}",
            "agent": "{{ agent| }}",
            "sub_tasks": [{"id": "implement", "prompt": "{{ implement_prompt }}"}],
        },
    })
    executions = {
        "include": [{
            "path": "signals/review.yaml",
            "with": {
                "repository": "my-repo",
                "implement_prompt": "./prompts/implement.md",
            },
        }],
    }
    # Should not raise — agent is referenced in template but uses its default (empty string)
    resolved = resolve_execution_includes(executions, config_dir)
    assert resolved["review-loop"]["agent"] == ""
