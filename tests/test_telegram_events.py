from pathlib import Path
from unittest.mock import patch

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
from propagate_telegram.bot import _format_event_reply


def test_format_waiting_for_signal_with_execution():
    event = {"event": "waiting_for_signal", "execution": "deploy-app", "signal": "review_done", "metadata": {}}
    result = _format_event_reply(event)
    assert result == "Waiting for signal 'review_done' (execution 'deploy-app')."


def test_format_waiting_for_signal_without_execution():
    event = {"event": "waiting_for_signal", "execution": "", "signal": "review_done", "metadata": {}}
    result = _format_event_reply(event)
    assert result == "Waiting for signal 'review_done'."


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

        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        assert call_args[0][1] == "waiting_for_signal"
        assert call_args[0][2]["signal"] == "go"
        assert call_args[0][2]["metadata"] == metadata
        assert call_args[0][2]["task_id"] == ""

        t.join(timeout=5)
    finally:
        close_pull_socket(pull_socket, address)
