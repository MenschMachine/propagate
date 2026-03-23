from unittest.mock import patch

import pytest

from propagate_app.cli import fail_command, main
from propagate_app.errors import PropagateError, UnableToImplementError
from propagate_app.models import AgentConfig, Config, ExecutionConfig, RepositoryConfig, RuntimeContext
from propagate_app.scheduler import run_execution_schedule


def test_fail_command_raises_unable_to_implement() -> None:
    with pytest.raises(UnableToImplementError, match="upstream backend bug"):
        fail_command("unable-to-implement", "Blocked by upstream backend bug")


def test_fail_command_unknown_kind_raises() -> None:
    with pytest.raises(PropagateError, match="Unknown failure kind 'not-a-real-kind'"):
        fail_command("not-a-real-kind", "nope")


def test_main_fail_command_returns_error_exit_code() -> None:
    result = main(["fail", "unable-to-implement", "Blocked by upstream backend bug"])
    assert result == 1


def test_scheduler_preserves_unable_to_implement_as_terminal_error(tmp_path) -> None:
    config_path = tmp_path / "propagate.yaml"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    config = Config(
        version="6",
        agent=AgentConfig(agents={"default": "echo {prompt_file}"}, default_agent="default"),
        repositories={"repo": RepositoryConfig(name="repo", path=repo_path)},
        context_sources={},
        signals={},
        propagation_triggers=[],
        executions={
            "review-loop": ExecutionConfig(
                name="review-loop",
                repository="repo",
                depends_on=[],
                signals=[],
                sub_tasks=[],
                git=None,
            )
        },
        config_path=config_path,
    )
    runtime_context = RuntimeContext(
        agents=config.agent.agents,
        default_agent=config.agent.default_agent,
        context_sources={},
        active_signal=None,
        initialized_signal_context_dirs=set(),
        working_dir=repo_path,
        context_root=tmp_path / ".context",
    )

    with patch(
        "propagate_app.scheduler.run_configured_execution",
        side_effect=UnableToImplementError("Blocked by upstream backend bug"),
    ):
        with pytest.raises(UnableToImplementError, match="Execution 'review-loop' failed while running"):
            run_execution_schedule(config, "review-loop", runtime_context)
