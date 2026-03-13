from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Sequence

from .errors import PropagateError


def build_agent_command(agent_command: str, prompt_file: Path) -> str:
    return agent_command.replace("{prompt_file}", shlex.quote(str(prompt_file)))


def run_agent_command(
    command: str,
    working_dir: Path,
    task_id: str,
    extra_env: dict[str, str] | None = None,
) -> None:
    run_shell_command(
        command,
        working_dir,
        failure_message=f"Agent command failed for sub-task '{task_id}' with exit code {{exit_code}}.",
        start_failure_message=f"Failed to start agent command for sub-task '{task_id}': {{error}}",
        extra_env=extra_env,
    )


def run_shell_command(
    command: str,
    working_dir: Path,
    failure_message: str,
    start_failure_message: str,
    *,
    capture_output: bool = False,
    text: bool = False,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = None
    if extra_env:
        env = {**os.environ, **extra_env}
    try:
        return subprocess.run(
            command,
            shell=True,
            cwd=working_dir,
            check=True,
            capture_output=capture_output,
            text=text,
            env=env,
        )
    except subprocess.CalledProcessError as error:
        raise PropagateError(failure_message.format(exit_code=error.returncode)) from error
    except OSError as error:
        raise PropagateError(start_failure_message.format(error=error)) from error


def run_process_command(
    command: Sequence[str],
    working_dir: Path,
    failure_message: str,
    start_failure_message: str,
    *,
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=working_dir,
            check=check,
            capture_output=capture_output,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise PropagateError(build_process_failure_message(failure_message, error)) from error
    except OSError as error:
        raise PropagateError(start_failure_message.format(error=error)) from error


def build_process_failure_message(
    failure_message: str,
    error: subprocess.CalledProcessError,
) -> str:
    message = failure_message.format(exit_code=error.returncode)
    stderr_excerpt = format_stderr_excerpt(error.stderr)
    if stderr_excerpt is None:
        return message
    return f"{message} stderr: {stderr_excerpt}"


def format_stderr_excerpt(stderr: str | None) -> str | None:
    if stderr is None:
        return None
    excerpt = " ".join(stderr.strip().split())
    if not excerpt:
        return None
    if len(excerpt) <= 240:
        return excerpt
    return f"{excerpt[:237].rstrip()}..."


def run_git_command(
    git_args: Sequence[str],
    working_dir: Path,
    failure_message: str,
    start_failure_message: str,
    *,
    capture_output: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run_process_command(
        ["git", *git_args],
        working_dir,
        failure_message=failure_message,
        start_failure_message=start_failure_message,
        capture_output=capture_output,
        check=check,
    )
