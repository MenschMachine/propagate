from __future__ import annotations

import pytest

from propagate_app.config_executions import parse_execution_signals
from propagate_app.context_store import ensure_context_dir, get_context_root, get_execution_context_dir, write_context_value
from propagate_app.errors import PropagateError
from propagate_app.graph import parse_propagation_trigger
from propagate_app.models import (
    ActiveSignal,
    AgentConfig,
    Config,
    ExecutionConfig,
    ExecutionGraph,
    ExecutionSignalConfig,
    ExecutionStatus,
    PropagationTriggerConfig,
    RepositoryConfig,
    SignalConfig,
    SignalFieldConfig,
    SubTaskConfig,
)
from propagate_app.scheduler import activate_matching_triggers, has_pending_signal_triggers
from propagate_app.signals import ensure_execution_accepts_signal, select_initial_execution, signal_payload_matches_when

# --- signal_payload_matches_when ---


def test_matches_when_none():
    assert signal_payload_matches_when({"label": "deploy"}, None) is True


def test_matches_when_match():
    assert signal_payload_matches_when({"label": "deploy"}, {"label": "deploy"}) is True


def test_matches_when_mismatch():
    assert signal_payload_matches_when({"label": "staging"}, {"label": "deploy"}) is False


def test_matches_when_missing_key():
    assert signal_payload_matches_when({}, {"label": "deploy"}) is False


def test_matches_when_multi_field():
    payload = {"label": "deploy", "env": "prod"}
    assert signal_payload_matches_when(payload, {"label": "deploy", "env": "prod"}) is True
    assert signal_payload_matches_when(payload, {"label": "deploy", "env": "staging"}) is False


def test_matches_when_equals_context(tmp_path):
    context_dir = tmp_path / "deploy"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":expected-label", "deploy")
    signal_config = SignalConfig(
        name="pull_request.labeled",
        payload={"label": SignalFieldConfig(field_type="string", required=False)},
    )
    assert signal_payload_matches_when(
        {"label": "deploy"},
        {"label": {"equals_context": ":expected-label"}},
        context_dir,
        signal_config,
    ) is True


def test_matches_when_equals_context_number_uses_context_string(tmp_path):
    context_dir = tmp_path / "deploy"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":expected-pr-number", "42")
    signal_config = SignalConfig(
        name="pull_request.labeled",
        payload={"pr_number": SignalFieldConfig(field_type="number", required=False)},
    )
    assert signal_payload_matches_when(
        {"pr_number": 42},
        {"pr_number": {"equals_context": ":expected-pr-number"}},
        context_dir,
        signal_config,
    ) is True


def test_matches_when_equals_context_missing_value_returns_false(tmp_path):
    context_dir = tmp_path / "deploy"
    ensure_context_dir(context_dir)
    signal_config = SignalConfig(
        name="pull_request.labeled",
        payload={"label": SignalFieldConfig(field_type="string", required=False)},
    )
    assert signal_payload_matches_when(
        {"label": "deploy"},
        {"label": {"equals_context": ":expected-label"}},
        context_dir,
        signal_config,
    ) is False


def test_matches_when_equals_context_boolean_uses_typed_resolution(tmp_path):
    context_dir = tmp_path / "deploy"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":expected-ready", "True")
    signal_config = SignalConfig(
        name="pull_request.labeled",
        payload={"ready": SignalFieldConfig(field_type="boolean", required=False)},
    )
    assert signal_payload_matches_when(
        {"ready": True},
        {"ready": {"equals_context": ":expected-ready"}},
        context_dir,
        signal_config,
    ) is True


# --- helpers ---


def _sig(name, **fields):
    """Build a minimal SignalConfig for testing."""
    payload = {k: SignalFieldConfig(field_type="string", required=False) for k in fields}
    return SignalConfig(name=name, payload=payload)


_RUN_SIG = _sig("run")
_PR_LABELED_SIG = _sig("pull_request.labeled", label="", repository="")


# --- parse_execution_signals ---


def test_parse_execution_signals_plain_string():
    result = parse_execution_signals("ex", ["run"], {"run": _RUN_SIG})
    assert len(result) == 1
    assert result[0].signal_name == "run"
    assert result[0].when is None


def test_parse_execution_signals_dict_with_when():
    result = parse_execution_signals(
        "ex",
        [{"signal": "pull_request.labeled", "when": {"label": "deploy"}}],
        {"pull_request.labeled": _PR_LABELED_SIG},
    )
    assert len(result) == 1
    assert result[0].signal_name == "pull_request.labeled"
    assert result[0].when == {"label": "deploy"}


def test_parse_execution_signals_mixed():
    result = parse_execution_signals(
        "ex",
        ["run", {"signal": "pull_request.labeled", "when": {"label": "deploy"}}],
        {"run": _RUN_SIG, "pull_request.labeled": _PR_LABELED_SIG},
    )
    assert len(result) == 2
    assert result[0].signal_name == "run"
    assert result[1].signal_name == "pull_request.labeled"
    assert result[1].when == {"label": "deploy"}


def test_parse_execution_signals_dict_without_when():
    result = parse_execution_signals(
        "ex",
        [{"signal": "run"}],
        {"run": _RUN_SIG},
    )
    assert result[0].when is None


def test_parse_execution_signals_dict_with_empty_when_matches_any_payload():
    result = parse_execution_signals(
        "ex",
        [{"signal": "pull_request.labeled", "when": {}}],
        {"pull_request.labeled": _PR_LABELED_SIG},
    )
    assert result[0].when == {}


def test_parse_execution_signals_dict_when_not_mapping():
    with pytest.raises(PropagateError, match="'when' must be a mapping"):
        parse_execution_signals("ex", [{"signal": "run", "when": "bad"}], {"run": _RUN_SIG})


def test_parse_execution_signals_dict_missing_signal_key():
    with pytest.raises(PropagateError, match="non-empty 'signal' key"):
        parse_execution_signals("ex", [{"when": {"label": "x"}}], {})


def test_parse_execution_signals_invalid_type():
    with pytest.raises(PropagateError, match="must be a string or a mapping"):
        parse_execution_signals("ex", [42], {})


def test_parse_execution_signals_when_unknown_field():
    with pytest.raises(PropagateError, match="unknown payload field 'bogus'"):
        parse_execution_signals(
            "ex",
            [{"signal": "run", "when": {"bogus": "x"}}],
            {"run": _RUN_SIG},
        )


def test_parse_execution_signals_when_equals_context():
    result = parse_execution_signals(
        "ex",
        [{"signal": "pull_request.labeled", "when": {"label": {"equals_context": ":expected-label"}}}],
        {"pull_request.labeled": _PR_LABELED_SIG},
    )
    assert result[0].when == {"label": {"equals_context": ":expected-label"}}


def test_parse_execution_signals_when_equals_context_invalid_key():
    with pytest.raises(PropagateError, match="reserved ':'-prefixed context key"):
        parse_execution_signals(
            "ex",
            [{"signal": "pull_request.labeled", "when": {"label": {"equals_context": "expected-label"}}}],
            {"pull_request.labeled": _PR_LABELED_SIG},
        )


def test_parse_execution_signals_when_equals_context_empty_mapping():
    with pytest.raises(PropagateError, match="must not be an empty mapping"):
        parse_execution_signals(
            "ex",
            [{"signal": "pull_request.labeled", "when": {"label": {}}}],
            {"pull_request.labeled": _PR_LABELED_SIG},
        )


# --- parse_propagation_trigger with when ---


_SIG_WITH_LABEL = _sig("sig", label="")


def test_propagation_trigger_with_when():
    trigger = parse_propagation_trigger(
        1,
        {"after": "a", "run": "b", "on_signal": "sig", "when": {"label": "deploy"}},
        {"a", "b"},
        {"sig": _SIG_WITH_LABEL},
    )
    assert trigger.when == {"label": "deploy"}


def test_propagation_trigger_when_without_on_signal():
    with pytest.raises(PropagateError, match="when requires on_signal"):
        parse_propagation_trigger(
            1,
            {"after": "a", "run": "b", "when": {"label": "deploy"}},
            {"a", "b"},
            {},
        )


def test_propagation_trigger_when_not_dict():
    with pytest.raises(PropagateError, match="when must be a mapping"):
        parse_propagation_trigger(
            1,
            {"after": "a", "run": "b", "on_signal": "sig", "when": "bad"},
            {"a", "b"},
            {"sig": _SIG_WITH_LABEL},
        )


def test_propagation_trigger_without_when():
    trigger = parse_propagation_trigger(
        1,
        {"after": "a", "run": "b", "on_signal": "sig"},
        {"a", "b"},
        {"sig": _SIG_WITH_LABEL},
    )
    assert trigger.when is None


def test_propagation_trigger_when_unknown_field():
    with pytest.raises(PropagateError, match="unknown payload field 'bogus'"):
        parse_propagation_trigger(
            1,
            {"after": "a", "run": "b", "on_signal": "sig", "when": {"bogus": "x"}},
            {"a", "b"},
            {"sig": _SIG_WITH_LABEL},
        )


def test_propagation_trigger_when_equals_context():
    trigger = parse_propagation_trigger(
        1,
        {"after": "a", "run": "b", "on_signal": "sig", "when": {"label": {"equals_context": ":expected-label"}}},
        {"a", "b"},
        {"sig": _SIG_WITH_LABEL},
    )
    assert trigger.when == {"label": {"equals_context": ":expected-label"}}


def test_propagation_trigger_when_context():
    trigger = parse_propagation_trigger(
        1,
        {"after": "a", "run": "b", "when_context": ":run-full"},
        {"a", "b"},
        {},
    )
    assert trigger.when_context == ":run-full"


# --- activate_matching_triggers with when ---


def _make_config(tmp_path, executions, triggers, signals=None):
    config_path = tmp_path / "propagate.yaml"
    config_path.touch()
    repos = {}
    for ex in executions:
        if ex.repository not in repos:
            repo_dir = tmp_path / ex.repository
            repo_dir.mkdir(exist_ok=True)
            repos[ex.repository] = RepositoryConfig(name=ex.repository, path=repo_dir)
    return Config(
        version="6",
        agent=AgentConfig(agents={"default": "echo test"}, default_agent="default"),
        repositories=repos,
        context_sources={},
        signals=signals or {"sig": _SIG_WITH_LABEL},
        propagation_triggers=triggers,
        executions={e.name: e for e in executions},
        config_path=config_path,
    )


def _make_execution(name):
    return ExecutionConfig(
        name=name,
        repository="repo",
        depends_on=[],
        signals=[],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )


def test_activate_triggers_when_matches(tmp_path):
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="sig", when={"label": "deploy"})
    config = _make_config(tmp_path, [_make_execution("a"), _make_execution("b")], [trigger])
    graph = ExecutionGraph(
        execution_order=("a", "b"),
        triggers_by_after={"a": (trigger,), "b": ()},
    )
    active = ActiveSignal(signal_type="sig", payload={"label": "deploy"}, source="cli")
    executions: dict[str, ExecutionStatus] = {"a": ExecutionStatus(state="completed")}
    activate_matching_triggers(config, graph, "a", active, executions)
    assert "b" in executions and executions["b"].state != "inactive"


def test_activate_triggers_when_no_match(tmp_path):
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="sig", when={"label": "deploy"})
    config = _make_config(tmp_path, [_make_execution("a"), _make_execution("b")], [trigger])
    graph = ExecutionGraph(
        execution_order=("a", "b"),
        triggers_by_after={"a": (trigger,), "b": ()},
    )
    active = ActiveSignal(signal_type="sig", payload={"label": "staging"}, source="cli")
    executions: dict[str, ExecutionStatus] = {"a": ExecutionStatus(state="completed")}
    activate_matching_triggers(config, graph, "a", active, executions)
    assert "b" not in executions


def test_activate_triggers_when_equals_context_matches(tmp_path):
    trigger = PropagationTriggerConfig(
        after="a",
        run="b",
        on_signal="sig",
        when={"label": {"equals_context": ":expected-label"}},
    )
    config = _make_config(tmp_path, [_make_execution("a"), _make_execution("b")], [trigger])
    graph = ExecutionGraph(
        execution_order=("a", "b"),
        triggers_by_after={"a": (trigger,), "b": ()},
    )
    context_dir = get_execution_context_dir(get_context_root(config.config_path), "a")
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":expected-label", "deploy")
    active = ActiveSignal(signal_type="sig", payload={"label": "deploy"}, source="cli")
    executions: dict[str, ExecutionStatus] = {"a": ExecutionStatus(state="completed")}
    activate_matching_triggers(config, graph, "a", active, executions)
    assert "b" in executions and executions["b"].state != "inactive"


def test_activate_triggers_when_none_still_fires(tmp_path):
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="sig", when=None)
    config = _make_config(tmp_path, [_make_execution("a"), _make_execution("b")], [trigger])
    graph = ExecutionGraph(
        execution_order=("a", "b"),
        triggers_by_after={"a": (trigger,), "b": ()},
    )
    active = ActiveSignal(signal_type="sig", payload={"label": "anything"}, source="cli")
    executions: dict[str, ExecutionStatus] = {"a": ExecutionStatus(state="completed")}
    activate_matching_triggers(config, graph, "a", active, executions)
    assert "b" in executions and executions["b"].state != "inactive"


def test_activate_triggers_when_context_matches(tmp_path):
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal=None, when_context=":run-full")
    config = _make_config(tmp_path, [_make_execution("a"), _make_execution("b")], [trigger], signals={})
    graph = ExecutionGraph(
        execution_order=("a", "b"),
        triggers_by_after={"a": (trigger,), "b": ()},
    )
    context_dir = get_execution_context_dir(get_context_root(config.config_path), "a")
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":run-full", "true")
    executions: dict[str, ExecutionStatus] = {"a": ExecutionStatus(state="completed")}
    activate_matching_triggers(config, graph, "a", None, executions)
    assert "b" in executions and executions["b"].state != "inactive"


def test_activate_triggers_when_context_mismatch(tmp_path):
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal=None, when_context=":run-full")
    config = _make_config(tmp_path, [_make_execution("a"), _make_execution("b")], [trigger], signals={})
    graph = ExecutionGraph(
        execution_order=("a", "b"),
        triggers_by_after={"a": (trigger,), "b": ()},
    )
    executions: dict[str, ExecutionStatus] = {"a": ExecutionStatus(state="completed")}
    activate_matching_triggers(config, graph, "a", None, executions)
    assert "b" not in executions


def test_activate_triggers_when_context_negated_missing_matches(tmp_path):
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal=None, when_context="!:run-full")
    config = _make_config(tmp_path, [_make_execution("a"), _make_execution("b")], [trigger], signals={})
    graph = ExecutionGraph(
        execution_order=("a", "b"),
        triggers_by_after={"a": (trigger,), "b": ()},
    )
    executions: dict[str, ExecutionStatus] = {"a": ExecutionStatus(state="completed")}
    activate_matching_triggers(config, graph, "a", None, executions)
    assert "b" in executions and executions["b"].state != "inactive"


def test_activate_triggers_when_context_missing_is_falsy(tmp_path):
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal=None, when_context=":run-full")
    config = _make_config(tmp_path, [_make_execution("a"), _make_execution("b")], [trigger], signals={})
    graph = ExecutionGraph(
        execution_order=("a", "b"),
        triggers_by_after={"a": (trigger,), "b": ()},
    )
    executions: dict[str, ExecutionStatus] = {"a": ExecutionStatus(state="completed")}
    activate_matching_triggers(config, graph, "a", None, executions)
    assert "b" not in executions


# --- has_pending_signal_triggers with when ---


def test_pending_trigger_with_when_stays_pending_after_signal_received(tmp_path):
    """A trigger with 'when' should remain pending even after receiving the signal type,
    because the payload may not have matched."""
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="sig", when={"label": "deploy"})
    config = _make_config(tmp_path, [_make_execution("a"), _make_execution("b")], [trigger])
    graph = ExecutionGraph(
        execution_order=("a", "b"),
        triggers_by_after={"a": (trigger,), "b": ()},
    )
    executions: dict[str, ExecutionStatus] = {"a": ExecutionStatus(state="completed")}
    # Signal type was received but payload didn't match — trigger should still be pending
    received = {"sig"}
    assert has_pending_signal_triggers(config, graph, executions, received) is True


def test_pending_trigger_without_when_resolved_after_signal_received(tmp_path):
    """A trigger without 'when' should be resolved once the signal type is received."""
    trigger = PropagationTriggerConfig(after="a", run="b", on_signal="sig", when=None)
    config = _make_config(tmp_path, [_make_execution("a"), _make_execution("b")], [trigger])
    graph = ExecutionGraph(
        execution_order=("a", "b"),
        triggers_by_after={"a": (trigger,), "b": ()},
    )
    executions: dict[str, ExecutionStatus] = {"a": ExecutionStatus(state="completed")}
    received = {"sig"}
    assert has_pending_signal_triggers(config, graph, executions, received) is False


# --- select_initial_execution with when ---


def _make_full_config(tmp_path, executions):
    config_path = tmp_path / "propagate.yaml"
    config_path.touch()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(exist_ok=True)
    return Config(
        version="6",
        agent=AgentConfig(agents={"default": "echo test"}, default_agent="default"),
        repositories={"repo": RepositoryConfig(name="repo", path=repo_dir)},
        context_sources={},
        signals={"pull_request.labeled": SignalConfig(name="pull_request.labeled", payload={
            "label": SignalFieldConfig(field_type="string", required=True),
            "pr_number": SignalFieldConfig(field_type="number", required=False),
        })},
        propagation_triggers=[],
        executions={e.name: e for e in executions},
        config_path=config_path,
    )


def test_select_initial_execution_when_filters(tmp_path):
    ex_deploy = ExecutionConfig(
        name="deploy",
        repository="repo",
        depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="pull_request.labeled", when={"label": "deploy"})],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    ex_test = ExecutionConfig(
        name="test",
        repository="repo",
        depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="pull_request.labeled", when={"label": "test"})],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    config = _make_full_config(tmp_path, [ex_deploy, ex_test])
    signal = ActiveSignal(signal_type="pull_request.labeled", payload={"label": "deploy"}, source="cli")
    result = select_initial_execution(config, None, signal)
    assert result.name == "deploy"


def test_select_initial_execution_multiple_when_match_error_lists_names(tmp_path):
    sub_tasks = [SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])]
    ex_a = ExecutionConfig(
        name="a", repository="repo", depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="pull_request.labeled", when={"label": "deploy"})],
        sub_tasks=sub_tasks, git=None,
    )
    ex_b = ExecutionConfig(
        name="b", repository="repo", depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="pull_request.labeled", when={"label": "deploy"})],
        sub_tasks=sub_tasks, git=None,
    )
    config = _make_full_config(tmp_path, [ex_a, ex_b])
    signal = ActiveSignal(signal_type="pull_request.labeled", payload={"label": "deploy"}, source="cli")
    with pytest.raises(PropagateError, match="a, b.*narrow 'when' filters"):
        select_initial_execution(config, None, signal)


# --- ensure_execution_accepts_signal with when ---


def test_ensure_accepts_signal_when_match():
    ex = ExecutionConfig(
        name="deploy", repository="repo", depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="pull_request.labeled", when={"label": "deploy"})],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    signal = ActiveSignal(signal_type="pull_request.labeled", payload={"label": "deploy"}, source="cli")
    ensure_execution_accepts_signal(ex, signal)  # should not raise


def test_ensure_accepts_signal_when_mismatch_gives_payload_error():
    ex = ExecutionConfig(
        name="deploy", repository="repo", depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="pull_request.labeled", when={"label": "deploy"})],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    signal = ActiveSignal(signal_type="pull_request.labeled", payload={"label": "staging"}, source="cli")
    with pytest.raises(PropagateError, match="payload does not match.*'when' filter"):
        ensure_execution_accepts_signal(ex, signal)


def test_ensure_accepts_signal_wrong_type_gives_allowed_signals_error():
    ex = ExecutionConfig(
        name="deploy", repository="repo", depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="pull_request.labeled")],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    signal = ActiveSignal(signal_type="push", payload={}, source="cli")
    with pytest.raises(PropagateError, match="does not accept signal 'push'"):
        ensure_execution_accepts_signal(ex, signal)


def test_select_initial_execution_when_no_match(tmp_path):
    ex = ExecutionConfig(
        name="deploy",
        repository="repo",
        depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="pull_request.labeled", when={"label": "deploy"})],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    config = _make_full_config(tmp_path, [ex])
    signal = ActiveSignal(signal_type="pull_request.labeled", payload={"label": "staging"}, source="cli")
    with pytest.raises(PropagateError, match="No execution accepts signal"):
        select_initial_execution(config, None, signal)


def test_select_initial_execution_when_equals_context(tmp_path):
    ex = ExecutionConfig(
        name="deploy",
        repository="repo",
        depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="pull_request.labeled", when={"pr_number": {"equals_context": ":expected-pr-number"}})],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    config = _make_full_config(tmp_path, [ex])
    context_dir = get_execution_context_dir(tmp_path / ".propagate-context-propagate", "deploy")
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":expected-pr-number", "42")
    signal = ActiveSignal(signal_type="pull_request.labeled", payload={"label": "deploy", "pr_number": 42}, source="cli")
    result = select_initial_execution(config, None, signal)
    assert result.name == "deploy"


def test_ensure_accepts_signal_when_equals_context_match(tmp_path):
    ex = ExecutionConfig(
        name="deploy", repository="repo", depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="pull_request.labeled", when={"pr_number": {"equals_context": ":expected-pr-number"}})],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    context_dir = tmp_path / "deploy"
    ensure_context_dir(context_dir)
    write_context_value(context_dir, ":expected-pr-number", "42")
    signal = ActiveSignal(signal_type="pull_request.labeled", payload={"label": "deploy", "pr_number": 42}, source="cli")
    signal_config = SignalConfig(
        name="pull_request.labeled",
        payload={
            "label": SignalFieldConfig(field_type="string", required=True),
            "pr_number": SignalFieldConfig(field_type="number", required=False),
        },
    )
    ensure_execution_accepts_signal(ex, signal, context_dir, signal_config)
