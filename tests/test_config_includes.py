from __future__ import annotations

from pathlib import Path

import pytest

from propagate_app.config_includes import render_included_value
from propagate_app.errors import PropagateError


def test_render_included_value_rejects_none_inside_larger_string(tmp_path: Path):
    with pytest.raises(PropagateError, match="non-scalar template parameter"):
        render_included_value(
            "prefix {{ value }} suffix",
            {"value": None},
            set(),
            tmp_path / "include.yaml",
        )


def test_render_included_value_rejects_list_inside_larger_string(tmp_path: Path):
    with pytest.raises(PropagateError, match="non-scalar template parameter"):
        render_included_value(
            "prefix {{ value }} suffix",
            {"value": ["a", "b"]},
            set(),
            tmp_path / "include.yaml",
        )
