from __future__ import annotations

from pathlib import Path


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
