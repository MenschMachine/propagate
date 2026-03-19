"""Tests for multi-config serve support."""

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


def test_multi_config_starts_thread_per_config(tmp_path):
    """Passing 2 configs spawns 2 threads, each calling _serve_one_config."""
    config_a = _make_config(tmp_path, "alpha")
    config_b = _make_config(tmp_path, "beta")

    calls = []

    def fake_serve_one(config, shutdown, resume):
        calls.append(config.config_path.stem)

    with (
        patch("propagate_app.serve.load_config", side_effect=[config_a, config_b]),
        patch("propagate_app.serve._serve_one_config", side_effect=fake_serve_one),
    ):
        serve_command([str(config_a.config_path), str(config_b.config_path)])

    assert sorted(calls) == ["alpha", "beta"]


def test_multi_config_shared_shutdown(tmp_path):
    """Setting shutdown from one thread causes both to exit."""
    config_a = _make_config(tmp_path, "alpha")
    config_b = _make_config(tmp_path, "beta")

    shutdown_events = []

    def fake_serve_one(config, shutdown, resume):
        shutdown_events.append(shutdown)
        if config.config_path.stem == "alpha":
            shutdown.set()
        else:
            # Wait a bit for the other thread to set shutdown
            shutdown.wait(timeout=2)

    with (
        patch("propagate_app.serve.load_config", side_effect=[config_a, config_b]),
        patch("propagate_app.serve._serve_one_config", side_effect=fake_serve_one),
    ):
        serve_command([str(config_a.config_path), str(config_b.config_path)])

    # Both threads got the same shutdown event
    assert len(shutdown_events) == 2
    assert shutdown_events[0] is shutdown_events[1]
    assert shutdown_events[0].is_set()


def test_single_config_backward_compatible(tmp_path):
    """A single-element list works exactly like the old string interface."""
    config = _make_config(tmp_path, "solo")

    calls = []

    def fake_serve_one(cfg, shutdown, resume):
        calls.append(cfg.config_path.stem)

    with (
        patch("propagate_app.serve.load_config", return_value=config),
        patch("propagate_app.serve._serve_one_config", side_effect=fake_serve_one),
    ):
        serve_command([str(config.config_path)])

    assert calls == ["solo"]


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

    with (
        patch("propagate_app.serve.load_config", side_effect=[config_a, config_b]),
        pytest.raises(PropagateError, match="Duplicate config name"),
    ):
        serve_command([str(config_a.config_path), str(config_b.config_path)])


def test_multi_config_thread_failure_sets_shutdown(tmp_path):
    """If one thread raises, the shutdown event is set so the other exits."""
    config_a = _make_config(tmp_path, "alpha")
    config_b = _make_config(tmp_path, "beta")

    shutdown_seen = []

    def fake_serve_one(config, shutdown, resume):
        if config.config_path.stem == "alpha":
            raise RuntimeError("bind failed")
        # beta waits for shutdown
        shutdown.wait(timeout=5)
        shutdown_seen.append(shutdown.is_set())

    with (
        patch("propagate_app.serve.load_config", side_effect=[config_a, config_b]),
        patch("propagate_app.serve._serve_one_config", side_effect=fake_serve_one),
    ):
        result = serve_command([str(config_a.config_path), str(config_b.config_path)])

    assert result == 1
    assert shutdown_seen == [True]


def test_multi_config_thread_failure_logged(tmp_path, caplog):
    """Thread failure is logged."""
    import logging

    config_a = _make_config(tmp_path, "alpha")
    config_b = _make_config(tmp_path, "beta")

    def fake_serve_one(config, shutdown, resume):
        if config.config_path.stem == "alpha":
            raise RuntimeError("socket bind failed")
        shutdown.wait(timeout=5)

    with (
        patch("propagate_app.serve.load_config", side_effect=[config_a, config_b]),
        patch("propagate_app.serve._serve_one_config", side_effect=fake_serve_one),
        caplog.at_level(logging.ERROR),
    ):
        serve_command([str(config_a.config_path), str(config_b.config_path)])

    assert any("alpha" in r.message and "socket bind failed" in r.message for r in caplog.records)
