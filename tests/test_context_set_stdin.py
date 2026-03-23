from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from propagate_app.cli import main
from propagate_app.context_store import read_context_value


def test_set_stdin_reads_from_stdin(tmp_path: Path) -> None:
    value = "Hello `world` with backticks"
    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = value
        with patch.dict("os.environ", {"PROPAGATE_CONTEXT_ROOT": str(tmp_path), "PROPAGATE_EXECUTION": "test-exec"}):
            rc = main(["context", "set", "--stdin", ":findings"])
    assert rc == 0
    stored = read_context_value(tmp_path / "test-exec", ":findings")
    assert stored == value


def test_set_stdin_preserves_backticks(tmp_path: Path) -> None:
    value = "Found `com.example.Foo` and `bar.Baz` issues"
    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = value
        with patch.dict("os.environ", {"PROPAGATE_CONTEXT_ROOT": str(tmp_path), "PROPAGATE_EXECUTION": "test-exec"}):
            rc = main(["context", "set", "--stdin", ":review"])
    assert rc == 0
    stored = read_context_value(tmp_path / "test-exec", ":review")
    assert stored == value


def test_set_stdin_and_value_are_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["context", "set", "--stdin", ":key", "some-value"])


def test_set_value_positional_still_works(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"PROPAGATE_CONTEXT_ROOT": str(tmp_path), "PROPAGATE_EXECUTION": "test-exec"}):
        rc = main(["context", "set", ":key", "hello world"])
    assert rc == 0
    stored = read_context_value(tmp_path / "test-exec", ":key")
    assert stored == "hello world"


def test_set_no_value_no_stdin_fails() -> None:
    with pytest.raises(SystemExit):
        main(["context", "set", ":key"])
