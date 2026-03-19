from pathlib import Path
from unittest.mock import patch

from propagate_app.event_format import format_event_reply as _format_event_reply
from propagate_app.git_runtime import create_execution_git_pr
from propagate_app.models import (
    GitBranchConfig,
    GitCommitConfig,
    GitConfig,
    GitPrConfig,
    GitPushConfig,
    GitRunState,
    PreparedGitExecution,
    RuntimeContext,
)
from propagate_app.signal_transport import publish_event_if_available


def test_format_waiting_for_signal_with_execution():
    event = {"event": "waiting_for_signal", "execution": "deploy-app", "signal": "review_done", "metadata": {}}
    result = _format_event_reply(event)
    assert result == "Waiting for signal 'review_done' (execution 'deploy-app')."


def test_format_waiting_for_signal_without_execution():
    event = {"event": "waiting_for_signal", "execution": "", "signal": "review_done", "metadata": {}}
    result = _format_event_reply(event)
    assert result == "Waiting for signal 'review_done'."


def test_format_signal_received_with_execution():
    event = {"event": "signal_received", "execution": "deploy-app", "signal": "review_done", "metadata": {}}
    result = _format_event_reply(event)
    assert result == "Signal 'review_done' received — resuming execution 'deploy-app'."


def test_format_signal_received_without_execution():
    event = {"event": "signal_received", "execution": "", "signal": "review_done", "metadata": {}}
    result = _format_event_reply(event)
    assert result == "Signal 'review_done' received — resuming."


def test_format_pr_created():
    event = {"event": "pr_created", "execution": "deploy-app", "pr_url": "https://github.com/org/repo/pull/42", "metadata": {}}
    result = _format_event_reply(event)
    assert result == "PR created for 'deploy-app':\nhttps://github.com/org/repo/pull/42"


def test_publish_event_if_available_noop_when_none():
    # Should not raise when pub_socket is None
    publish_event_if_available(None, "test_event", {"key": "value"})


def test_format_run_completed_still_works():
    event = {"event": "run_completed", "signal_type": "deploy", "messages": ["done"]}
    result = _format_event_reply(event)
    assert "Run completed" in result
    assert "deploy" in result


def test_format_command_failed_still_works():
    event = {"event": "command_failed", "command": "resume", "message": "No state file."}
    result = _format_event_reply(event)
    assert result == "Command /resume failed: No state file."


# ---------------------------------------------------------------------------
# Integration: pr_created publish from git_runtime
# ---------------------------------------------------------------------------


def _make_runtime_context(context_root: Path, pub_socket=None, metadata=None) -> RuntimeContext:
    return RuntimeContext(
        agent_command="echo",
        context_sources={},
        active_signal=None,
        initialized_signal_context_dirs=set(),
        working_dir=Path("."),
        context_root=context_root,
        execution_name="my-exec",
        task_id="",
        git_state=GitRunState(),
        pub_socket=pub_socket,
        metadata=metadata or {},
    )


def test_pr_created_event_published(tmp_path):
    pr_config = GitPrConfig(base="main", draft=False)
    git_config = GitConfig(
        branch=GitBranchConfig(name="feat/x", base="main", reuse=True),
        commit=GitCommitConfig(message_source=None, message_key=":msg"),
        push=GitPushConfig(remote="origin"),
        pr=pr_config,
    )
    prepared = PreparedGitExecution(starting_branch="main", selected_branch="feat/x")
    metadata = {"chat_id": "123"}
    rc = _make_runtime_context(tmp_path, pub_socket="fake_socket", metadata=metadata)

    with patch("propagate_app.git_runtime.create_pull_request", return_value="https://github.com/org/repo/pull/42"), \
         patch("propagate_app.git_runtime.publish_event_if_available") as mock_publish:
        create_execution_git_pr("my-exec", git_config, prepared, "Subject\n\nBody", rc)

    mock_publish.assert_called_once_with("fake_socket", "pr_created", {
        "execution": "my-exec",
        "pr_url": "https://github.com/org/repo/pull/42",
        "metadata": metadata,
    })


def test_pr_created_event_not_published_when_no_url(tmp_path):
    pr_config = GitPrConfig(base="main", draft=False)
    git_config = GitConfig(
        branch=GitBranchConfig(name="feat/x", base="main", reuse=True),
        commit=GitCommitConfig(message_source=None, message_key=":msg"),
        push=GitPushConfig(remote="origin"),
        pr=pr_config,
    )
    prepared = PreparedGitExecution(starting_branch="main", selected_branch="feat/x")
    rc = _make_runtime_context(tmp_path, pub_socket="fake_socket")

    with patch("propagate_app.git_runtime.create_pull_request", return_value=""), \
         patch("propagate_app.git_runtime.publish_event_if_available") as mock_publish:
        create_execution_git_pr("my-exec", git_config, prepared, "Subject\n\nBody", rc)

    mock_publish.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: scheduler-level waiting_for_signal publish
# ---------------------------------------------------------------------------


def test_scheduler_wait_publishes_event(tmp_path):
    import threading

    from propagate_app.graph import build_execution_graph
    from propagate_app.models import (
        AgentConfig,
        Config,
        ExecutionConfig,
        ExecutionScheduleState,
        PropagationTriggerConfig,
        RepositoryConfig,
        SignalConfig,
        SubTaskConfig,
    )
    from propagate_app.scheduler import _wait_for_signal
    from propagate_app.signal_transport import bind_pull_socket, close_pull_socket, close_push_socket, connect_push_socket, send_signal

    config_path = tmp_path / "propagate.yaml"
    config_path.touch()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    exec_a = ExecutionConfig(
        name="a", repository="repo", depends_on=[], signals=[],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    exec_b = ExecutionConfig(
        name="b", repository="repo", depends_on=[], signals=[],
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    config = Config(
        version="6",
        agent=AgentConfig(command="echo test"),
        repositories={"repo": RepositoryConfig(name="repo", path=repo_dir)},
        context_sources={},
        signals={"go": SignalConfig(name="go", payload={})},
        propagation_triggers=[PropagationTriggerConfig(after="a", run="b", on_signal="go", when=None)],
        executions={"a": exec_a, "b": exec_b},
        config_path=config_path,
    )
    execution_graph = build_execution_graph(config)
    schedule_state = ExecutionScheduleState(
        active_names={"a"},
        completed_names={"a"},
    )
    received = set()
    metadata = {"chat_id": "99"}
    rc = _make_runtime_context(tmp_path, pub_socket="fake", metadata=metadata)

    import tempfile
    sock_dir = tempfile.mkdtemp()
    address = f"ipc://{sock_dir}/t.sock"
    pull_socket = bind_pull_socket(address)

    # Send the signal in a background thread so _wait_for_signal unblocks
    def send_after_delay():
        push = connect_push_socket(address)
        send_signal(push, "go", {})
        close_push_socket(push)

    try:
        t = threading.Thread(target=send_after_delay)
        t.start()

        with patch("propagate_app.scheduler.publish_event_if_available") as mock_publish:
            _wait_for_signal(pull_socket, config, execution_graph, schedule_state, received, rc)

        assert mock_publish.call_count == 2
        # First call: waiting_for_signal
        waiting_call = mock_publish.call_args_list[0]
        assert waiting_call[0][1] == "waiting_for_signal"
        assert waiting_call[0][2]["signal"] == "go"
        assert waiting_call[0][2]["metadata"] == metadata
        assert waiting_call[0][2]["task_id"] == ""
        # Second call: signal_received
        received_call = mock_publish.call_args_list[1]
        assert received_call[0][1] == "signal_received"
        assert received_call[0][2]["signal"] == "go"
        assert received_call[0][2]["metadata"] == metadata

        t.join(timeout=5)
    finally:
        close_pull_socket(pull_socket, address)


# ---------------------------------------------------------------------------
# Integration: sub-task level signal_received publish
# ---------------------------------------------------------------------------


def test_subtask_signal_received_event_published(tmp_path):
    import threading

    from propagate_app.models import (
        ExecutionConfig,
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

    address = socket_address(tmp_path / "test-received-event.yaml")
    socket = bind_pull_socket(address)
    try:
        sub_tasks = [
            SubTaskConfig(
                task_id="wait",
                prompt_path=None,
                before=[],
                after=[],
                on_failure=[],
                wait_for_signal="review_done",
                routes=[SubTaskRouteConfig(when={"status": "approved"}, continue_flow=True)],
            ),
        ]
        execution = ExecutionConfig(
            name="my-exec", repository="repo", depends_on=[], signals=[],
            sub_tasks=sub_tasks, git=None,
        )
        metadata = {"chat_id": "42"}
        rc = _make_runtime_context(tmp_path, pub_socket="fake", metadata=metadata)
        rc = RuntimeContext(
            agent_command="echo",
            context_sources={},
            active_signal=None,
            initialized_signal_context_dirs=set(),
            working_dir=Path("."),
            context_root=tmp_path,
            execution_name="my-exec",
            task_id="",
            signal_socket=socket,
            pub_socket="fake",
            metadata=metadata,
        )

        def send():
            push = connect_push_socket(address)
            send_signal(push, "review_done", {"status": "approved"})
            close_push_socket(push)

        t = threading.Thread(target=send, daemon=True)
        t.start()

        with patch("propagate_app.sub_tasks.publish_event_if_available") as mock_publish:
            run_execution_sub_tasks(execution, rc)

        t.join(timeout=5)

        # Should have two calls: waiting_for_signal and signal_received
        assert mock_publish.call_count == 2
        waiting_call = mock_publish.call_args_list[0]
        assert waiting_call[0][1] == "waiting_for_signal"
        received_call = mock_publish.call_args_list[1]
        assert received_call[0][1] == "signal_received"
        assert received_call[0][2]["execution"] == "my-exec"
        assert received_call[0][2]["signal"] == "review_done"
        assert received_call[0][2]["metadata"] == metadata
    finally:
        close_pull_socket(socket, address)
