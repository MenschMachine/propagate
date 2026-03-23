"""Verify PR interaction commands use context keys with the colon prefix.

Context keys like ':review-body' are stored on disk with the colon as part of the
filename. The git runtime functions must not strip the colon when reading/writing.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from propagate_app.context_store import write_context_value
from propagate_app.git_runtime import (
    git_do_pr_comment_add,
    git_do_pr_comments_list,
    git_do_pr_labels_add,
    git_do_pr_labels_list,
    git_do_pr_labels_remove,
    resolve_label_args,
)
from propagate_app.models import RuntimeContext


@pytest.fixture()
def ctx(tmp_path: Path):
    context_root = tmp_path / ".propagate-context"
    context_root.mkdir()
    exec_dir = context_root / "test-exec"
    exec_dir.mkdir()
    working_dir = tmp_path / "repo"
    working_dir.mkdir()
    rc = RuntimeContext(
        agents={"default": "true"},
        default_agent="default",
        context_sources={},
        active_signal=None,
        initialized_signal_context_dirs=set(),
        context_root=context_root,
        execution_name="test-exec",
        task_id="",
        working_dir=working_dir,
    )
    return rc, exec_dir


def test_resolve_label_args_reads_colon_prefixed_file(ctx):
    rc, exec_dir = ctx
    write_context_value(exec_dir, ":my-label", "bug-fix")
    resolved = resolve_label_args([":my-label"], exec_dir)
    assert resolved == ["bug-fix"]


def test_pr_comment_add_reads_colon_prefixed_key(ctx):
    rc, exec_dir = ctx
    write_context_value(exec_dir, ":review-body", "Great work!")
    with patch("propagate_app.git_runtime.add_pr_comment") as mock_comment:
        git_do_pr_comment_add("test-exec", ":review-body", rc)
    mock_comment.assert_called_once_with("Great work!", rc.working_dir)


def test_pr_labels_list_writes_colon_prefixed_key(ctx):
    rc, exec_dir = ctx
    fake_json = '{"labels": [{"name": "bug"}]}'
    with patch("propagate_app.git_runtime.list_pr_labels", return_value=fake_json):
        git_do_pr_labels_list("test-exec", ":stored-labels", rc)
    stored = (exec_dir / ":stored-labels").read_text(encoding="utf-8")
    assert stored == fake_json


def test_pr_comments_list_writes_colon_prefixed_key(ctx):
    rc, exec_dir = ctx
    fake_json = '{"comments": []}'
    with patch("propagate_app.git_runtime.list_pr_comments", return_value=fake_json):
        git_do_pr_comments_list("test-exec", ":stored-comments", rc)
    stored = (exec_dir / ":stored-comments").read_text(encoding="utf-8")
    assert stored == fake_json


def test_pr_labels_add_resolves_colon_prefixed_key(ctx):
    rc, exec_dir = ctx
    write_context_value(exec_dir, ":label-key", "enhancement")
    with patch("propagate_app.git_runtime.add_pr_labels") as mock_add:
        git_do_pr_labels_add("test-exec", [":label-key"], rc)
    mock_add.assert_called_once_with(["enhancement"], rc.working_dir)


def test_pr_labels_remove_resolves_colon_prefixed_key(ctx):
    rc, exec_dir = ctx
    write_context_value(exec_dir, ":remove-key", "stale")
    with patch("propagate_app.git_runtime.remove_pr_labels") as mock_remove:
        git_do_pr_labels_remove("test-exec", [":remove-key"], rc)
    mock_remove.assert_called_once_with(["stale"], rc.working_dir)
