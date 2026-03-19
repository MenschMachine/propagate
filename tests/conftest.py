from __future__ import annotations

from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption("--slow", action="store_true", default=False, help="include slow tests")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--slow"):
        return
    skip = pytest.mark.skip(reason="use --slow to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


def inject_test_repository(
    executions: dict[str, object],
    workspace: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    """Auto-inject a 'workspace' repository into executions that lack a repository field.

    Returns (repositories_dict, patched_executions_dict).
    """
    repositories: dict[str, object] = {"workspace": {"path": str(workspace)}}
    patched: dict[str, object] = {}
    for name, execution in executions.items():
        if isinstance(execution, dict) and "repository" not in execution:
            patched[name] = {"repository": "workspace", **execution}
        else:
            patched[name] = execution
    return repositories, patched
