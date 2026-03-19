"""Tests for wait_for_signal sub-task routing (loop support)."""

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from propagate_app.config_executions import parse_sub_task
from propagate_app.context_store import ensure_context_dir, resolve_execution_context_dir, write_context_value
from propagate_app.errors import PropagateError
from propagate_app.execution_flow import run_configured_execution
from propagate_app.models import (
    ActiveSignal,
    ExecutionConfig,
    RuntimeContext,
    SignalConfig,
    SignalFieldConfig,
    SubTaskConfig,
    SubTaskRouteConfig,
)
from propagate_app.signal_transport import (
    bind_pull_socket,
    close_pull_socket,
    close_push_socket,
    connect_push_socket,
    send_signal,
    socket_address,
)
from propagate_app.sub_tasks import run_execution_sub_tasks

# ---------------------------------------------------------------------------
# Config parse tests
# ---------------------------------------------------------------------------


SIGNAL_CONFIGS = {
    "pull_request.labeled": SignalConfig(
        name="pull_request.labeled",
        payload={
            "label": SignalFieldConfig(field_type="string", required=True),
            "repository": SignalFieldConfig(field_type="string", required=True),
            "pr_number": SignalFieldConfig(field_type="number", required=True),
        },
    ),
}


def test_parse_wait_for_signal_valid(tmp_path):
    seen_ids = {"code", "review"}
    result = parse_sub_task(
        "ex", 3,
        {
            "id": "wait",
            "wait_for_signal": "pull_request.labeled",
            "routes": [
                {"when": {"label": "changes_required"}, "goto": "code"},
                {"when": {"label": "approved"}, "continue": True},
            ],
        },
        tmp_path, set(), SIGNAL_CONFIGS, seen_ids,
    )
    assert result.wait_for_signal == "pull_request.labeled"
    assert len(result.routes) == 2
    assert result.routes[0].goto == "code"
    assert result.routes[0].continue_flow is False
    assert result.routes[1].goto is None
    assert result.routes[1].continue_flow is True


def test_parse_wait_for_signal_valid_equals_context(tmp_path):
    seen_ids = {"code", "review"}
    result = parse_sub_task(
        "ex", 3,
        {
            "id": "wait",
            "wait_for_signal": "pull_request.labeled",
            "routes": [
                {"when": {"pr_number": {"equals_context": ":api-docs-pr-number"}}, "continue": True},
            ],
        },
        tmp_path, set(), SIGNAL_CONFIGS, seen_ids,
    )
    assert result.routes[0].when == {"pr_number": {"equals_context": ":api-docs-pr-number"}}


def test_parse_wait_for_signal_without_routes_raises(tmp_path):
    with pytest.raises(PropagateError, match="both be present"):
        parse_sub_task("ex", 1, {"id": "w", "wait_for_signal": "pull_request.labeled"}, tmp_path, set(), SIGNAL_CONFIGS)


def test_parse_routes_without_wait_for_signal_raises(tmp_path):
    with pytest.raises(PropagateError, match="both be present"):
        parse_sub_task(
            "ex", 1,
            {"id": "w", "routes": [{"when": {"label": "x"}, "continue": True}]},
            tmp_path, set(),
        )


def test_parse_wait_for_signal_unknown_signal_raises(tmp_path):
    with pytest.raises(PropagateError, match="unknown signal"):
        parse_sub_task(
            "ex", 1,
            {"id": "w", "wait_for_signal": "nonexistent", "routes": [{"when": {"x": 1}, "continue": True}]},
            tmp_path, set(), SIGNAL_CONFIGS,
        )


def test_parse_wait_for_signal_with_prompt_raises(tmp_path):
    prompt = tmp_path / "p.md"
    prompt.write_text("hi")
    with pytest.raises(PropagateError, match="must not have 'prompt'"):
        parse_sub_task(
            "ex", 1,
            {"id": "w", "prompt": str(prompt), "wait_for_signal": "pull_request.labeled", "routes": [{"when": {"label": "x"}, "continue": True}]},
            tmp_path, set(), SIGNAL_CONFIGS,
        )


def test_parse_wait_for_signal_with_before_allowed(tmp_path):
    result = parse_sub_task(
        "ex", 1,
        {"id": "w", "before": ["echo hi"], "wait_for_signal": "pull_request.labeled", "routes": [{"when": {"label": "x"}, "continue": True}]},
        tmp_path, set(), SIGNAL_CONFIGS,
    )
    assert result.before == ["echo hi"]
    assert result.wait_for_signal == "pull_request.labeled"


def test_parse_wait_for_signal_with_after_allowed(tmp_path):
    result = parse_sub_task(
        "ex", 1,
        {"id": "w", "after": ["echo done"], "wait_for_signal": "pull_request.labeled", "routes": [{"when": {"label": "x"}, "continue": True}]},
        tmp_path, set(), SIGNAL_CONFIGS,
    )
    assert result.after == ["echo done"]


def test_parse_wait_for_signal_with_on_failure_raises(tmp_path):
    with pytest.raises(PropagateError, match="must not have 'on_failure'"):
        parse_sub_task(
            "ex", 1,
            {"id": "w", "on_failure": ["echo fail"], "wait_for_signal": "pull_request.labeled", "routes": [{"when": {"label": "x"}, "continue": True}]},
            tmp_path, set(), SIGNAL_CONFIGS,
        )


def test_parse_route_goto_unknown_task_raises(tmp_path):
    seen_ids = {"code"}
    with pytest.raises(PropagateError, match="unknown sub-task 'nonexistent'"):
        parse_sub_task(
            "ex", 2,
            {
                "id": "wait",
                "wait_for_signal": "pull_request.labeled",
                "routes": [{"when": {"label": "x"}, "goto": "nonexistent"}],
            },
            tmp_path, set(), SIGNAL_CONFIGS, seen_ids,
        )


def test_parse_route_both_goto_and_continue_raises(tmp_path):
    seen_ids = {"code"}
    with pytest.raises(PropagateError, match="exactly one"):
        parse_sub_task(
            "ex", 2,
            {
                "id": "wait",
                "wait_for_signal": "pull_request.labeled",
                "routes": [{"when": {"label": "x"}, "goto": "code", "continue": True}],
            },
            tmp_path, set(), SIGNAL_CONFIGS, seen_ids,
        )


def test_parse_route_neither_goto_nor_continue_raises(tmp_path):
    with pytest.raises(PropagateError, match="exactly one"):
        parse_sub_task(
            "ex", 2,
            {
                "id": "wait",
                "wait_for_signal": "pull_request.labeled",
                "routes": [{"when": {"label": "x"}}],
            },
            tmp_path, set(), SIGNAL_CONFIGS,
        )


def test_parse_route_equals_context_invalid_key_raises(tmp_path):
    with pytest.raises(PropagateError, match="reserved ':'-prefixed context key"):
        parse_sub_task(
            "ex", 2,
            {
                "id": "wait",
                "wait_for_signal": "pull_request.labeled",
                "routes": [{"when": {"pr_number": {"equals_context": "api-docs-pr-number"}}, "continue": True}],
            },
            tmp_path, set(), SIGNAL_CONFIGS,
        )


# ---------------------------------------------------------------------------
# Runtime tests
# ---------------------------------------------------------------------------


def _make_runtime_context(context_root: Path, signal_socket=None, signal_configs=None) -> RuntimeContext:
    return RuntimeContext(
        agent_command="echo",
        context_sources={},
        active_signal=None,
        initialized_signal_context_dirs=set(),
        signal_configs=signal_configs or {},
        working_dir=Path("."),
        context_root=context_root,
        execution_name="my-exec",
        task_id="",
        signal_socket=signal_socket,
    )


def _make_sub_task(task_id, prompt=False):
    return SubTaskConfig(
        task_id=task_id,
        prompt_path=None,
        before=[],
        after=[],
        on_failure=[],
    )


def _make_wait_task(task_id, signal_name, routes):
    return SubTaskConfig(
        task_id=task_id,
        prompt_path=None,
        before=[],
        after=[],
        on_failure=[],
        wait_for_signal=signal_name,
        routes=routes,
    )


def test_wait_for_signal_continue(tmp_path):
    """Signal arrives with 'approved' label -> continue flow, execution finishes."""
    address = socket_address(tmp_path / "test-continue.yaml")
    socket = bind_pull_socket(address)
    try:
        sub_tasks = [
            _make_sub_task("code"),
            _make_wait_task("wait", "pull_request.labeled", [
                SubTaskRouteConfig(when={"label": "changes_required"}, goto="code"),
                SubTaskRouteConfig(when={"label": "approved"}, continue_flow=True),
            ]),
            _make_sub_task("done"),
        ]
        execution = ExecutionConfig(
            name="my-exec", repository="repo", depends_on=[], signals=[],
            sub_tasks=sub_tasks, git=None,
        )
        ctx_dir = tmp_path / "my-exec"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        rc = _make_runtime_context(tmp_path, signal_socket=socket, signal_configs=SIGNAL_CONFIGS)

        # Send signal in a thread
        def send():
            push = connect_push_socket(address)
            send_signal(push, "pull_request.labeled", {"label": "approved", "repository": "org/repo", "pr_number": 1})
            close_push_socket(push)

        ran_tasks = []

        def tracking_run(exec_name, sub_task, rt_ctx, git_config=None, completed_phase=None, on_phase_completed=None):
            ran_tasks.append(sub_task.task_id)

        t = threading.Thread(target=send, daemon=True)
        t.start()

        with patch("propagate_app.sub_tasks.run_sub_task", side_effect=tracking_run):
            run_execution_sub_tasks(execution, rc)

        t.join(timeout=5)
        assert ran_tasks == ["code", "done"]
    finally:
        close_pull_socket(socket, address)


def test_wait_for_signal_goto_loops(tmp_path):
    """Signal arrives with 'changes_required' -> goto code, then 'approved' -> continue."""
    address = socket_address(tmp_path / "test-goto.yaml")
    socket = bind_pull_socket(address)
    try:
        sub_tasks = [
            _make_sub_task("code"),
            _make_sub_task("publish"),
            _make_wait_task("wait", "pull_request.labeled", [
                SubTaskRouteConfig(when={"label": "changes_required"}, goto="code"),
                SubTaskRouteConfig(when={"label": "approved"}, continue_flow=True),
            ]),
        ]
        execution = ExecutionConfig(
            name="my-exec", repository="repo", depends_on=[], signals=[],
            sub_tasks=sub_tasks, git=None,
        )
        ctx_dir = tmp_path / "my-exec"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        rc = _make_runtime_context(tmp_path, signal_socket=socket, signal_configs=SIGNAL_CONFIGS)

        def send():
            import time
            time.sleep(0.3)
            push = connect_push_socket(address)
            # First signal: changes_required
            send_signal(push, "pull_request.labeled", {"label": "changes_required", "repository": "org/repo", "pr_number": 1})
            time.sleep(0.5)
            # Second signal: approved
            send_signal(push, "pull_request.labeled", {"label": "approved", "repository": "org/repo", "pr_number": 1})
            close_push_socket(push)

        ran_tasks = []

        def tracking_run(exec_name, sub_task, rt_ctx, git_config=None, completed_phase=None, on_phase_completed=None):
            ran_tasks.append(sub_task.task_id)

        t = threading.Thread(target=send, daemon=True)
        t.start()

        with patch("propagate_app.sub_tasks.run_sub_task", side_effect=tracking_run):
            run_execution_sub_tasks(execution, rc)

        t.join(timeout=5)
        # code, publish, [wait -> goto code], code, publish, [wait -> continue]
        assert ran_tasks == ["code", "publish", "code", "publish"]
    finally:
        close_pull_socket(socket, address)


def test_wait_for_signal_runs_before_and_after_hooks(tmp_path):
    """before/after hooks execute around the wait_for_signal pause."""
    address = socket_address(tmp_path / "test-hooks.yaml")
    socket = bind_pull_socket(address)
    try:
        marker_before = tmp_path / "before_ran"
        marker_after = tmp_path / "after_ran"
        sub_tasks = [
            _make_wait_task("wait", "pull_request.labeled", [
                SubTaskRouteConfig(when={"label": "approved"}, continue_flow=True),
            ]),
            _make_sub_task("done"),
        ]
        # Add hooks to the wait task
        sub_tasks[0] = SubTaskConfig(
            task_id="wait",
            prompt_path=None,
            before=[f"touch {marker_before}"],
            after=[f"touch {marker_after}"],
            on_failure=[],
            wait_for_signal="pull_request.labeled",
            routes=[SubTaskRouteConfig(when={"label": "approved"}, continue_flow=True)],
        )
        execution = ExecutionConfig(
            name="my-exec", repository="repo", depends_on=[], signals=[],
            sub_tasks=sub_tasks, git=None,
        )
        rc = _make_runtime_context(tmp_path, signal_socket=socket, signal_configs=SIGNAL_CONFIGS)

        def send():
            push = connect_push_socket(address)
            send_signal(push, "pull_request.labeled", {"label": "approved", "repository": "org/repo", "pr_number": 1})
            close_push_socket(push)

        ran_tasks = []

        def tracking_run(exec_name, sub_task, rt_ctx, git_config=None, completed_phase=None, on_phase_completed=None):
            ran_tasks.append(sub_task.task_id)

        t = threading.Thread(target=send, daemon=True)
        t.start()

        with patch("propagate_app.sub_tasks.run_sub_task", side_effect=tracking_run):
            run_execution_sub_tasks(execution, rc)

        t.join(timeout=5)
        assert ran_tasks == ["done"]
        assert marker_before.exists(), "before hook should have run"
        assert marker_after.exists(), "after hook should have run"
    finally:
        close_pull_socket(socket, address)


def test_wait_for_signal_updates_active_signal_for_following_tasks(tmp_path):
    address = socket_address(tmp_path / "test-active-signal.yaml")
    socket = bind_pull_socket(address)
    try:
        sub_tasks = [
            _make_wait_task("wait", "pull_request.labeled", [
                SubTaskRouteConfig(when={"label": "approved"}, continue_flow=True),
            ]),
            _make_sub_task("done"),
        ]
        execution = ExecutionConfig(
            name="my-exec", repository="repo", depends_on=[], signals=[],
            sub_tasks=sub_tasks, git=None,
        )
        rc = RuntimeContext(
            agent_command="echo",
            context_sources={},
            active_signal=ActiveSignal(
                signal_type="pull_request.labeled",
                payload={"label": "suggestions_needed", "repository": "org/repo", "pr_number": 1},
                source="initial",
            ),
            initialized_signal_context_dirs=set(),
            working_dir=Path("."),
            context_root=tmp_path,
            execution_name="my-exec",
            task_id="",
            signal_socket=socket,
        )

        observed_pr_numbers = []

        def send():
            push = connect_push_socket(address)
            send_signal(push, "pull_request.labeled", {"label": "approved", "repository": "org/repo", "pr_number": 99})
            close_push_socket(push)

        def tracking_run(exec_name, sub_task, rt_ctx, git_config=None, completed_phase=None, on_phase_completed=None):
            observed_pr_numbers.append(rt_ctx.active_signal.payload["pr_number"])

        t = threading.Thread(target=send, daemon=True)
        t.start()

        with patch("propagate_app.sub_tasks.run_sub_task", side_effect=tracking_run):
            run_execution_sub_tasks(execution, rc)

        t.join(timeout=5)
        assert observed_pr_numbers == [99]
    finally:
        close_pull_socket(socket, address)


def test_wait_for_signal_updates_active_signal_for_execution_after_hooks(tmp_path):
    address = socket_address(tmp_path / "test-after-hooks-signal.yaml")
    socket = bind_pull_socket(address)
    try:
        observed_pr_numbers = []
        execution = ExecutionConfig(
            name="my-exec",
            repository="repo",
            depends_on=[],
            signals=[],
            sub_tasks=[
                _make_wait_task(
                    "wait",
                    "pull_request.labeled",
                    [SubTaskRouteConfig(when={"label": "approved"}, continue_flow=True)],
                ),
            ],
            git=None,
            after=["echo done"],
        )
        rc = RuntimeContext(
            agent_command="echo",
            context_sources={},
            active_signal=ActiveSignal(
                signal_type="pull_request.labeled",
                payload={"label": "suggestions_needed", "repository": "org/repo", "pr_number": 1},
                source="initial",
            ),
            initialized_signal_context_dirs=set(),
            working_dir=Path("."),
            context_root=tmp_path,
            execution_name="my-exec",
            task_id="",
            signal_socket=socket,
        )

        def send():
            push = connect_push_socket(address)
            send_signal(push, "pull_request.labeled", {"label": "approved", "repository": "org/repo", "pr_number": 99})
            close_push_socket(push)

        def fake_run_hook_phase(context_id, phase, actions, runtime_context, git_config=None):
            if context_id == "execution 'my-exec'" and phase == "after":
                observed_pr_numbers.append(runtime_context.active_signal.payload["pr_number"])

        t = threading.Thread(target=send, daemon=True)
        t.start()
        with patch("propagate_app.execution_flow.run_hook_phase", side_effect=fake_run_hook_phase):
            run_configured_execution(execution, rc)
        t.join(timeout=5)

        assert observed_pr_numbers == [99]
    finally:
        close_pull_socket(socket, address)


def test_wait_for_signal_route_equals_context_matches(tmp_path):
    address = socket_address(tmp_path / "test-equals-context.yaml")
    socket = bind_pull_socket(address)
    try:
        sub_tasks = [
            _make_wait_task("wait", "pull_request.labeled", [
                SubTaskRouteConfig(
                    when={
                        "label": "approved",
                        "pr_number": {"equals_context": ":api-docs-pr-number"},
                    },
                    continue_flow=True,
                ),
            ]),
            _make_sub_task("done"),
        ]
        execution = ExecutionConfig(
            name="my-exec", repository="repo", depends_on=[], signals=[],
            sub_tasks=sub_tasks, git=None,
        )
        rc = _make_runtime_context(tmp_path, signal_socket=socket, signal_configs=SIGNAL_CONFIGS)
        context_dir = resolve_execution_context_dir(rc)
        ensure_context_dir(context_dir)
        write_context_value(context_dir, ":api-docs-pr-number", "99")

        ran_tasks = []

        def send():
            push = connect_push_socket(address)
            send_signal(push, "pull_request.labeled", {"label": "approved", "repository": "org/repo", "pr_number": 99})
            close_push_socket(push)

        def tracking_run(exec_name, sub_task, rt_ctx, git_config=None, completed_phase=None, on_phase_completed=None):
            ran_tasks.append(sub_task.task_id)

        t = threading.Thread(target=send, daemon=True)
        t.start()

        with patch("propagate_app.sub_tasks.run_sub_task", side_effect=tracking_run):
            run_execution_sub_tasks(execution, rc)

        t.join(timeout=5)
        assert ran_tasks == ["done"]
    finally:
        close_pull_socket(socket, address)


def test_wait_for_signal_no_socket_raises(tmp_path):
    """wait_for_signal without a signal socket raises an error."""
    sub_tasks = [
        _make_wait_task("wait", "pull_request.labeled", [
            SubTaskRouteConfig(when={"label": "approved"}, continue_flow=True),
        ]),
    ]
    execution = ExecutionConfig(
        name="my-exec", repository="repo", depends_on=[], signals=[],
        sub_tasks=sub_tasks, git=None,
    )
    ctx_dir = tmp_path / "my-exec"
    ctx_dir.mkdir(parents=True, exist_ok=True)
    rc = _make_runtime_context(tmp_path, signal_socket=None)

    with pytest.raises(PropagateError, match="no signal socket"):
        run_execution_sub_tasks(execution, rc)
