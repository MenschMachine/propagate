from propagate_app.event_format import format_event_reply


def test_command_failed():
    event = {"event": "command_failed", "command": "resume", "message": "No state file found."}
    assert format_event_reply(event) == "Command /resume failed: No state file found."


def test_waiting_for_signal_with_execution():
    event = {"event": "waiting_for_signal", "signal": "deploy", "execution": "build"}
    assert format_event_reply(event) == "Waiting for signal 'deploy' (execution 'build')."


def test_waiting_for_signal_without_execution():
    event = {"event": "waiting_for_signal", "signal": "deploy"}
    assert format_event_reply(event) == "Waiting for signal 'deploy'."


def test_signal_received_with_execution():
    event = {"event": "signal_received", "signal": "deploy", "execution": "build"}
    assert format_event_reply(event) == "Signal 'deploy' received — resuming execution 'build'."


def test_signal_received_without_execution():
    event = {"event": "signal_received", "signal": "deploy"}
    assert format_event_reply(event) == "Signal 'deploy' received — resuming."


def test_pr_created():
    event = {"event": "pr_created", "execution": "build", "pr_url": "https://github.com/org/repo/pull/1"}
    assert format_event_reply(event) == "PR created for 'build':\nhttps://github.com/org/repo/pull/1"


def test_run_completed():
    event = {"event": "run_completed", "signal_type": "deploy"}
    assert format_event_reply(event) == "Run completed for signal 'deploy'."


def test_run_completed_with_messages():
    event = {"event": "run_completed", "signal_type": "deploy", "messages": ["Done.", "All good."]}
    result = format_event_reply(event)
    assert "Run completed for signal 'deploy'." in result
    assert "Done." in result
    assert "All good." in result


def test_run_failed():
    event = {"event": "run_failed", "signal_type": "deploy"}
    assert format_event_reply(event) == "Run failed for signal 'deploy'."


def test_unknown_event_type():
    event = {"event": "something_new", "data": "value"}
    assert format_event_reply(event) == "Event: something_new"
