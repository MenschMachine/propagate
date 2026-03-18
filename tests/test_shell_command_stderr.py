"""Test that run_shell_command signals stderr in error messages."""


import pytest

from propagate_app.errors import PropagateError
from propagate_app.processes import run_shell_command


def test_shell_command_includes_stderr_in_error(tmp_path):
    with pytest.raises(PropagateError, match="No such file"):
        run_shell_command(
            "python -c \"import sys; sys.stderr.write('No such file or directory\\n'); sys.exit(1)\"",
            tmp_path,
            failure_message="Command failed with exit code {exit_code}.",
            start_failure_message="Failed to start: {error}",
            capture_output=True,
            text=True,
        )


def test_shell_command_error_without_capture(tmp_path):
    with pytest.raises(PropagateError, match="exit code 1"):
        run_shell_command(
            "python -c \"import sys; sys.exit(1)\"",
            tmp_path,
            failure_message="Command failed with exit code {exit_code}.",
            start_failure_message="Failed to start: {error}",
        )
