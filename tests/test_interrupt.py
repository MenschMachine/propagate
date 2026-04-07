"""Tests for the agent interrupt -> interactive session -> resume feature."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from propagate_app.errors import AgentInterrupted, PropagateError
from propagate_app.interactive import ACTION_ABORT, ACTION_RERUN, ACTION_SKIP, handle_agent_interrupt, prompt_resume_action
from propagate_app.processes import build_interactive_agent_command

# --- build_interactive_agent_command ---


@pytest.mark.parametrize("agent_cmd,expected", [
    ("claude -p {prompt_file}", "claude -p"),
    ("claude --prompt-file {prompt_file}", "claude --prompt-file"),
    ("claude {prompt_file}", "claude"),
    ("my-agent --file {prompt_file} --verbose", "my-agent --file --verbose"),
])
def test_build_interactive_agent_command(agent_cmd, expected):
    assert build_interactive_agent_command(agent_cmd) == expected


# --- prompt_resume_action ---


@pytest.mark.parametrize("user_input,expected", [
    ("r", ACTION_RERUN),
    ("R", ACTION_RERUN),
    ("rerun", ACTION_RERUN),
    ("s", ACTION_SKIP),
    ("S", ACTION_SKIP),
    ("skip", ACTION_SKIP),
    ("a", ACTION_ABORT),
    ("A", ACTION_ABORT),
    ("abort", ACTION_ABORT),
])
def test_prompt_resume_action(user_input, expected):
    with patch("builtins.input", return_value=user_input):
        assert prompt_resume_action() == expected


def test_prompt_resume_action_eof():
    with patch("builtins.input", side_effect=EOFError):
        assert prompt_resume_action() == ACTION_ABORT


def test_prompt_resume_action_keyboard_interrupt():
    with patch("builtins.input", side_effect=KeyboardInterrupt):
        assert prompt_resume_action() == ACTION_ABORT


def test_prompt_resume_action_retries_on_invalid():
    with patch("builtins.input", side_effect=["x", "bad", "r"]):
        assert prompt_resume_action() == ACTION_RERUN


# --- AgentInterrupted exception ---


def test_agent_interrupted_is_propagate_error():
    exc = AgentInterrupted("msg", task_id="t1", working_dir=Path("/tmp"))
    assert isinstance(exc, PropagateError)


def test_agent_interrupted_carries_context():
    exc = AgentInterrupted("msg", task_id="t1", working_dir=Path("/repo"))
    exc.execution_name = "build"
    exc.agent_command = "claude -p {prompt_file}"
    assert exc.task_id == "t1"
    assert exc.working_dir == Path("/repo")
    assert exc.execution_name == "build"
    assert exc.agent_command == "claude -p {prompt_file}"


# --- run_agent_command interrupt handling ---


def test_run_agent_command_raises_agent_interrupted_on_keyboard_interrupt():
    import subprocess as real_subprocess

    from propagate_app.processes import run_agent_command

    mock_process = MagicMock()
    mock_process.stdout = _iter_raising_keyboard_interrupt(["line1\n", "line2\n"])
    mock_process.wait.return_value = 0
    mock_process.pid = 1234

    with patch("propagate_app.processes.subprocess") as mock_subprocess:
        mock_subprocess.Popen.return_value = mock_process
        mock_subprocess.TimeoutExpired = real_subprocess.TimeoutExpired
        with patch("propagate_app.processes.os.killpg"):
            with patch("propagate_app.processes.os.getpgid", return_value=1234):
                with pytest.raises(AgentInterrupted) as exc_info:
                    run_agent_command("echo hello", Path("/tmp"), "task-1")

    assert exc_info.value.task_id == "task-1"
    assert exc_info.value.working_dir == Path("/tmp")


def _iter_raising_keyboard_interrupt(lines):
    """Yield lines then raise KeyboardInterrupt."""
    for line in lines:
        yield line.encode()
    raise KeyboardInterrupt


# --- AgentInterrupted propagation through sub_task ---


def test_agent_interrupted_not_caught_by_on_failure():
    """AgentInterrupted must propagate through run_sub_task_agent without triggering on_failure."""
    from propagate_app.sub_tasks import run_sub_task_agent

    exc = AgentInterrupted("interrupted", task_id="t1", working_dir=Path("/tmp"))

    sub_task = MagicMock()
    sub_task.task_id = "t1"
    sub_task.on_failure = ["echo recovery"]

    runtime_context = MagicMock()
    runtime_context.execution_agent = "default"
    runtime_context.agents = {"default": "claude -p {prompt_file}"}
    runtime_context.execution_name = "build"
    runtime_context.working_dir = Path("/tmp")

    with patch("propagate_app.sub_tasks.run_agent_command", side_effect=exc):
        with patch("propagate_app.sub_tasks.build_agent_command", return_value="claude -p /tmp/prompt.md"):
            with patch("propagate_app.sub_tasks.build_context_env", return_value={}):
                with pytest.raises(AgentInterrupted) as exc_info:
                    run_sub_task_agent(sub_task, Path("/tmp/prompt.md"), runtime_context)

    assert exc_info.value.execution_name == "build"
    assert exc_info.value.agent_command == "claude -p {prompt_file}"


# --- AgentInterrupted propagation through execution_flow ---


def test_agent_interrupted_skips_on_failure_hooks_in_execution_flow():
    from propagate_app.execution_flow import run_configured_execution
    from propagate_app.models import RuntimeContext

    exc = AgentInterrupted("interrupted", task_id="t1", working_dir=Path("/tmp"))
    exc.execution_name = "build"
    exc.agent_command = "claude -p {prompt_file}"

    execution = MagicMock()
    execution.name = "build"
    execution.sub_tasks = []
    execution.before = []
    execution.after = []
    execution.on_failure = ["echo should-not-run"]
    execution.git = None
    execution.agent = None

    runtime_context = RuntimeContext(
        agents={},
        default_agent="",
        context_sources={},
        active_signal=None,
        initialized_signal_context_dirs=set(),
    )

    with patch("propagate_app.execution_flow.run_execution_sub_tasks", side_effect=exc):
        with patch("propagate_app.execution_flow.run_hook_phase") as mock_hook:
            with pytest.raises(AgentInterrupted):
                run_configured_execution(execution, runtime_context)
            for call in mock_hook.call_args_list:
                assert call[0][1] != "on_failure"


# --- handle_agent_interrupt ---


def test_handle_agent_interrupt_launches_interactive_session():
    exc = AgentInterrupted("interrupted", task_id="t1", working_dir=Path("/repo"))
    exc.execution_name = "build"
    exc.agent_command = "claude -p {prompt_file}"

    with patch("propagate_app.interactive.run_interactive_agent", return_value=0) as mock_run:
        with patch("propagate_app.interactive.prompt_resume_action", return_value=ACTION_RERUN):
            result = handle_agent_interrupt(exc)

    assert result == ACTION_RERUN
    mock_run.assert_called_once_with("claude -p", Path("/repo"))


# --- run_interactive_agent ---


def test_run_interactive_agent_returns_exit_code(tmp_path):
    from propagate_app.processes import run_interactive_agent

    result = run_interactive_agent("exit 0", tmp_path)
    assert result == 0


def test_run_interactive_agent_returns_nonzero_exit_code(tmp_path):
    from propagate_app.processes import run_interactive_agent

    result = run_interactive_agent("exit 42", tmp_path)
    assert result == 42


# --- _run_with_interrupt_handling ---


def test_run_with_interrupt_handling_rerun(tmp_path):
    from propagate_app.cli import _run_with_interrupt_handling
    from propagate_app.models import ExecutionStatus, RunState

    run_state = RunState(
        config_path=tmp_path / "config.yaml",
        initial_execution="build",
        executions={"build": ExecutionStatus(state="in_progress")},
        active_signal=None,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
    )
    call_count = 0

    def schedule_fn():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            exc = AgentInterrupted("interrupted", task_id="t1", working_dir=tmp_path)
            exc.execution_name = "build"
            exc.agent_command = "claude -p {prompt_file}"
            raise exc

    with patch("propagate_app.interactive.handle_agent_interrupt", return_value=ACTION_RERUN):
        result = _run_with_interrupt_handling(tmp_path / "config.yaml", run_state, schedule_fn)

    assert result == 0
    assert call_count == 2


def test_run_with_interrupt_handling_skip(tmp_path):
    from propagate_app.cli import _run_with_interrupt_handling
    from propagate_app.models import ExecutionStatus, RunState

    run_state = RunState(
        config_path=tmp_path / "config.yaml",
        initial_execution="build",
        executions={"build": ExecutionStatus(state="in_progress")},
        active_signal=None,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
    )
    call_count = 0

    def schedule_fn():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            exc = AgentInterrupted("interrupted", task_id="t1", working_dir=tmp_path)
            exc.execution_name = "build"
            exc.agent_command = "claude -p {prompt_file}"
            raise exc

    with patch("propagate_app.interactive.handle_agent_interrupt", return_value=ACTION_SKIP):
        with patch("propagate_app.run_state.save_run_state"):
            result = _run_with_interrupt_handling(tmp_path / "config.yaml", run_state, schedule_fn)

    assert result == 0
    assert call_count == 2
    ts = run_state.executions["build"].tasks.get("t1")
    assert ts is not None
    assert ts.phases.agent_completed is True


def test_run_with_interrupt_handling_abort(tmp_path):
    from propagate_app.cli import _run_with_interrupt_handling
    from propagate_app.models import ExecutionStatus, RunState

    state_file = tmp_path / ".propagate-state-config.yaml"
    state_file.touch()

    run_state = RunState(
        config_path=tmp_path / "config.yaml",
        initial_execution="build",
        executions={"build": ExecutionStatus(state="in_progress")},
        active_signal=None,
        cloned_repos={},
        initialized_signal_context_dirs=set(),
    )

    def schedule_fn():
        exc = AgentInterrupted("interrupted", task_id="t1", working_dir=tmp_path)
        exc.execution_name = "build"
        exc.agent_command = "claude -p {prompt_file}"
        raise exc

    with patch("propagate_app.interactive.handle_agent_interrupt", return_value=ACTION_ABORT):
        result = _run_with_interrupt_handling(tmp_path / "config.yaml", run_state, schedule_fn)

    assert result == 130


# --- request_agent_interrupt ---


def test_request_agent_interrupt_terminates_process():
    import propagate_app.processes as proc

    mock_process = MagicMock()
    mock_process.pid = 1234
    proc._interrupt_requested.clear()
    with proc._process_lock:
        proc._current_agent_process = mock_process
    try:
        with patch("propagate_app.processes.os.killpg"):
            with patch("propagate_app.processes.os.getpgid", return_value=1234):
                result = proc.request_agent_interrupt()
        assert result is True
        assert proc._interrupt_requested.is_set()
    finally:
        with proc._process_lock:
            proc._current_agent_process = None
        proc._interrupt_requested.clear()


def test_request_agent_interrupt_no_process():
    import propagate_app.processes as proc

    proc._interrupt_requested.clear()
    with proc._process_lock:
        proc._current_agent_process = None
    result = proc.request_agent_interrupt()
    assert result is False
    assert not proc._interrupt_requested.is_set()


def test_run_agent_command_raises_on_interrupt_event():
    """When _interrupt_requested is set externally (SIGUSR1), raise AgentInterrupted."""
    import subprocess as real_subprocess

    import propagate_app.processes as proc
    from propagate_app.processes import run_agent_command

    mock_process = MagicMock()

    def _stdout_with_interrupt():
        yield b"line1\n"
        # Simulate SIGUSR1 handler firing mid-stream: sets flag and terminates process
        proc._interrupt_requested.set()

    mock_process.stdout = _stdout_with_interrupt()
    mock_process.wait.return_value = -15

    with patch("propagate_app.processes.subprocess") as mock_subprocess:
        mock_subprocess.Popen.return_value = mock_process
        mock_subprocess.TimeoutExpired = real_subprocess.TimeoutExpired
        try:
            with pytest.raises(AgentInterrupted) as exc_info:
                run_agent_command("echo hello", Path("/tmp"), "task-1")
            assert exc_info.value.task_id == "task-1"
        finally:
            proc._interrupt_requested.clear()


# --- serve mode: _handle_agent_interrupted ---


def test_handle_agent_interrupted_publishes_event():
    from propagate_app.serve import _handle_agent_interrupted

    exc = AgentInterrupted("interrupted", task_id="t1", working_dir=Path("/repo"))
    exc.execution_name = "build"
    exc.agent_command = "claude -p {prompt_file}"

    mock_config = MagicMock()
    mock_signal_socket = MagicMock()
    mock_pub_socket = MagicMock()
    shutdown = MagicMock()
    shutdown.is_set.return_value = False

    # Simulate receiving interrupt_resume command on first poll
    with patch("propagate_app.serve.receive_message") as mock_recv:
        mock_recv.return_value = ("command", "interrupt_resume", {}, {"action": "abort"})
        with patch("propagate_app.serve.publish_event") as mock_pub:
            _handle_agent_interrupted(exc, mock_config, mock_signal_socket, mock_pub_socket, shutdown)

    mock_pub.assert_called_once_with(mock_pub_socket, "agent_interrupted", {
        "execution": "build",
        "task_id": "t1",
        "working_dir": "/repo",
        "agent_command": "claude -p {prompt_file}",
    })


def test_handle_agent_interrupted_skip_marks_complete(tmp_path):
    from propagate_app.serve import _handle_agent_interrupted

    exc = AgentInterrupted("interrupted", task_id="t1", working_dir=tmp_path)
    exc.execution_name = "build"
    exc.agent_command = "claude -p {prompt_file}"

    config = MagicMock()
    config.config_path = tmp_path / "config.yaml"
    shutdown = MagicMock()
    shutdown.is_set.return_value = False

    with patch("propagate_app.serve.receive_message") as mock_recv:
        mock_recv.return_value = ("command", "interrupt_resume", {}, {"action": "skip"})
        with patch("propagate_app.serve.publish_event"):
            with patch("propagate_app.serve._mark_interrupted_task_complete") as mock_mark:
                with patch("propagate_app.serve._resume_run"):
                    _handle_agent_interrupted(exc, config, MagicMock(), MagicMock(), shutdown)

    mock_mark.assert_called_once_with(config, exc)


# --- shell: _cmd_interrupt ---


def test_cmd_interrupt_sends_command_and_handles_event():
    from propagate_app.shell import _cmd_interrupt, _ShellState

    state = _ShellState()
    state.active_project = "myproject"
    state.projects = {"myproject": {}}

    mock_push = MagicMock()

    interrupt_token = "token-123"

    # Put unrelated events first, then the matching acknowledgement.
    state.response_queue.put({
        "event": "agent_interrupted",
        "project": "other-project",
        "interrupt_token": interrupt_token,
    })
    state.response_queue.put({
        "event": "interrupt_failed",
        "project": "myproject",
        "interrupt_token": "wrong-token",
    })
    state.response_queue.put({
        "event": "agent_interrupted",
        "project": "myproject",
        "interrupt_token": interrupt_token,
        "execution": "build",
        "task_id": "t1",
        "working_dir": "/repo",
        "agent_command": "claude -p {prompt_file}",
    })

    with patch("propagate_app.shell.send_command") as mock_send:
        with patch("propagate_app.shell.uuid.uuid4", return_value=interrupt_token):
            with patch("propagate_app.interactive.prompt_resume_action", return_value="rerun"):
                _cmd_interrupt(mock_push, state)

    # Should have sent interrupt + interrupt_resume
    calls = mock_send.call_args_list
    assert calls[0][0] == (mock_push, "interrupt")
    assert calls[0][1]["metadata"] == {
        "project": "myproject",
        "interrupt_token": interrupt_token,
    }
    assert calls[1][0] == (mock_push, "interrupt_resume")
    assert calls[1][1]["metadata"] == {
        "project": "myproject",
        "interrupt_token": interrupt_token,
        "action": "rerun",
    }


def test_cmd_interrupt_uses_enriched_followup_event_for_display(capsys):
    from propagate_app.shell import _cmd_interrupt, _ShellState

    state = _ShellState()
    state.active_project = "myproject"
    state.projects = {"myproject": {}}
    mock_push = MagicMock()
    interrupt_token = "token-456"

    state.response_queue.put({
        "event": "agent_interrupted",
        "project": "myproject",
        "interrupt_token": interrupt_token,
        "execution": "build",
        "task_id": "summarize",
        "working_dir": "/repo",
    })

    with patch("propagate_app.shell.send_command"):
        with patch("propagate_app.shell.uuid.uuid4", return_value=interrupt_token):
            with patch("propagate_app.interactive.prompt_resume_action", return_value="skip"):
                _cmd_interrupt(mock_push, state)

    out = capsys.readouterr().out
    assert "Interrupted execution 'build', task 'summarize'." in out
    assert "Working directory: /repo" in out


def test_cmd_interrupt_falls_back_when_context_not_available(capsys):
    from propagate_app.shell import _cmd_interrupt, _ShellState

    state = _ShellState()
    state.active_project = "myproject"
    state.projects = {"myproject": {}}
    mock_push = MagicMock()
    interrupt_token = "token-789"

    state.response_queue.put({
        "event": "agent_interrupted",
        "project": "myproject",
        "interrupt_token": interrupt_token,
        "acknowledged": True,
    })

    with patch("propagate_app.shell.send_command"):
        with patch("propagate_app.shell.uuid.uuid4", return_value=interrupt_token):
            with patch("propagate_app.interactive.prompt_resume_action", return_value="abort"):
                _cmd_interrupt(mock_push, state)

    out = capsys.readouterr().out
    assert "Interrupt failed: worker returned an interrupt acknowledgment without required context." in out
