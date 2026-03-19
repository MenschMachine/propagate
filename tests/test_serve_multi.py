"""Tests for multi-config serve support via coordinator."""

from unittest.mock import patch

import pytest

from propagate_app.errors import PropagateError
from propagate_app.models import (
    AgentConfig,
    Config,
    ExecutionConfig,
    ExecutionSignalConfig,
    RepositoryConfig,
    SignalConfig,
    SubTaskConfig,
)
from propagate_app.serve import serve_command


def _make_config(tmp_path, name, signals=None, subdir=None):
    if subdir:
        parent = tmp_path / subdir
        parent.mkdir(parents=True, exist_ok=True)
    else:
        parent = tmp_path
    config_path = parent / f"{name}.yaml"
    config_path.touch()
    repo_dir = tmp_path / f"repo-{name}"
    repo_dir.mkdir(exist_ok=True)
    exec_cfg = ExecutionConfig(
        name=f"exec-{name}",
        repository=f"repo-{name}",
        depends_on=[],
        signals=[ExecutionSignalConfig(signal_name="go")] if signals is None else signals,
        sub_tasks=[SubTaskConfig(task_id="t1", prompt_path=None, before=[], after=[], on_failure=[])],
        git=None,
    )
    return Config(
        version="6",
        agent=AgentConfig(command="echo test"),
        repositories={f"repo-{name}": RepositoryConfig(name=f"repo-{name}", path=repo_dir)},
        context_sources={},
        signals=signals or {"go": SignalConfig(name="go", payload={})},
        propagation_triggers=[],
        executions={exec_cfg.name: exec_cfg},
        config_path=config_path,
    )


def test_multi_config_coordinator_spawns_workers(tmp_path):
    """Passing 2 configs spawns 2 workers via coordinator."""
    config_a = _make_config(tmp_path, "alpha")
    config_b = _make_config(tmp_path, "beta")

    with (
        patch("propagate_app.coordinator.Coordinator.start") as mock_start,
        patch("propagate_app.coordinator.Coordinator.run"),
    ):
        serve_command([str(config_a.config_path), str(config_b.config_path)])
        mock_start.assert_called_once()
        args = mock_start.call_args
        assert len(args[0][0]) == 2


def test_single_config_backward_compatible(tmp_path):
    """A single-element list works through coordinator."""
    config = _make_config(tmp_path, "solo")

    with (
        patch("propagate_app.coordinator.Coordinator.start") as mock_start,
        patch("propagate_app.coordinator.Coordinator.run"),
    ):
        serve_command([str(config.config_path)])
        mock_start.assert_called_once()
        args = mock_start.call_args
        assert len(args[0][0]) == 1


def test_multi_config_isolated_sockets(tmp_path):
    """Each config gets different ZMQ addresses derived from its path."""
    from propagate_app.signal_transport import pub_socket_address, socket_address

    config_a = _make_config(tmp_path, "alpha")
    config_b = _make_config(tmp_path, "beta")

    addr_a = socket_address(config_a.config_path)
    addr_b = socket_address(config_b.config_path)
    pub_a = pub_socket_address(config_a.config_path)
    pub_b = pub_socket_address(config_b.config_path)

    assert addr_a != addr_b
    assert pub_a != pub_b


def test_multi_config_duplicate_stems_rejected(tmp_path):
    """Two configs with the same filename stem are rejected."""
    config_a = _make_config(tmp_path, "propagate", subdir="a")
    config_b = _make_config(tmp_path, "propagate", subdir="b")

    with pytest.raises(PropagateError, match="Duplicate config name"):
        serve_command([str(config_a.config_path), str(config_b.config_path)])


def test_no_configs_starts_empty_coordinator(tmp_path):
    """Passing no configs starts coordinator with empty worker list."""
    with (
        patch("propagate_app.coordinator.Coordinator.start") as mock_start,
        patch("propagate_app.coordinator.Coordinator.run"),
    ):
        serve_command([])
        mock_start.assert_called_once()
        args = mock_start.call_args
        assert args[0][0] == []
