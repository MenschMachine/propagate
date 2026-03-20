from __future__ import annotations

from pathlib import Path

from propagate_app.context_store import context_delete_command, write_context_value


def test_delete_existing_key(tmp_path: Path) -> None:
    write_context_value(tmp_path, ":review-findings", "some findings")
    assert (tmp_path / ":review-findings").is_file()

    rc = context_delete_command(":review-findings", tmp_path)

    assert rc == 0
    assert not (tmp_path / ":review-findings").exists()


def test_delete_nonexistent_key(tmp_path: Path) -> None:
    rc = context_delete_command(":review-findings", tmp_path)
    assert rc == 0


def test_delete_respects_key_validation(tmp_path: Path) -> None:
    import pytest

    from propagate_app.errors import PropagateError

    with pytest.raises(PropagateError):
        context_delete_command("invalid key!", tmp_path)
