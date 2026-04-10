from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from propagate import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "config" / "scripts"))

from changed_url_payload import build_changed_url_payload  # noqa: E402
from track_implementations_from_indexing import (  # noqa: E402
    load_payload,
    normalize_change,
    parse_issue_like_body,
    suggestion_type_from_metadata,
)


def test_request_indexing_config_loads_with_tracking_execution() -> None:
    config = load_config(REPO_ROOT / "config" / "seo-track-and-index.yaml")

    assert config.version == "6"
    assert tuple(config.repositories) == ("pdfdancer-www", "pdfdancer-marketing-data")
    assert tuple(config.executions) == ("detect-changes", "track-implementations", "request-index")

    detect = config.executions["detect-changes"]
    assert detect.repository == "pdfdancer-www"
    assert [task.task_id for task in detect.sub_tasks] == ["capture-changed-urls"]
    assert ':changed-url-payload' in detect.sub_tasks[0].before

    track = config.executions["track-implementations"]
    assert track.repository == "pdfdancer-marketing-data"
    assert track.git is not None

    request = config.executions["request-index"]
    assert request.repository == "pdfdancer-www"
    assert request.depends_on == ["track-implementations"]

    triggers = {(t.after, t.run, t.when_context) for t in config.propagation_triggers}
    assert ("detect-changes", "track-implementations", None) in triggers
    assert ("track-implementations", "request-index", None) in triggers


def test_build_changed_url_payload_detects_lastmod_deltas() -> None:
    outputs = {
        "old": json.dumps({"/sdk/nodejs/": "a", "/sdk/python/": "a"}),
        "new": json.dumps({"/sdk/nodejs/": "b", "/sdk/python/": "a", "/sdk/java/": "c"}),
    }

    def fake_runner(cmd, capture_output, text, check):
        class Result:
            def __init__(self, stdout: str = "") -> None:
                self.stdout = stdout

        if cmd[:3] == ["git", "rev-parse", "--verify"]:
            return Result("ok")
        if cmd[:2] == ["git", "fetch"]:
            return Result("")
        ref = cmd[2].split(":", 1)[0]
        return Result(outputs[ref])

    payload = build_changed_url_payload("old", "new", runner=fake_runner)

    assert payload["before"] == "old"
    assert payload["after"] == "new"
    assert payload["changed_paths"] == ["/sdk/java/", "/sdk/nodejs/"]
    assert payload["changed_urls"] == [
        "https://pdfdancer.com/sdk/java/",
        "https://pdfdancer.com/sdk/nodejs/",
    ]


def test_parse_issue_body_and_type_mapping() -> None:
    body = """---

**Page:** `/sdk/fastapi/`
**Action:** `new-page`
**Diagnosis:** `technical`

---

### What to do

1. **Change type:** `new-page` (create from scratch)
2. **Must change:** create a dedicated `/sdk/fastapi/` page with implementation-first content.
"""

    parsed = parse_issue_like_body(body)

    assert parsed["page"] == "/sdk/fastapi/"
    assert parsed["action"] == "new-page"
    assert parsed["diagnosis"] == "technical"
    assert suggestion_type_from_metadata(parsed["action"], parsed["diagnosis"]) == "technical"
    assert normalize_change(parsed["change_type"], parsed["must_change"], parsed["page"]) == (
        "create a dedicated `/sdk/fastapi/` page with implementation-first content."
    )


def test_changed_url_payload_reports_count() -> None:
    outputs = {
        "old": json.dumps({"/sdk/nodejs/": "a"}),
        "new": json.dumps({"/sdk/nodejs/": "b"}),
    }

    def fake_runner(cmd, capture_output, text, check):
        class Result:
            def __init__(self, stdout: str = "") -> None:
                self.stdout = stdout

        if cmd[:3] == ["git", "rev-parse", "--verify"]:
            return Result("ok")
        if cmd[:2] == ["git", "fetch"]:
            return Result("")
        ref = cmd[2].split(":", 1)[0]
        return Result(outputs[ref])

    payload = build_changed_url_payload("old", "new", runner=fake_runner)

    assert payload["changed_count"] == 1


def test_changed_url_payload_rejects_invalid_ref() -> None:
    outputs = {
        "new": json.dumps({"/sdk/nodejs/": "b"}),
    }

    def fake_runner(cmd, capture_output, text, check):
        class Result:
            def __init__(self, stdout: str = "", returncode: int = 0) -> None:
                self.stdout = stdout
                self.returncode = returncode

        if cmd[:3] == ["git", "rev-parse", "--verify"]:
            if cmd[3].startswith("bad-ref"):
                raise subprocess.CalledProcessError(128, cmd, output="", stderr="fatal: bad revision")
            return Result("ok")
        if cmd[:2] == ["git", "fetch"]:
            return Result("")
        ref = cmd[2].split(":", 1)[0]
        return Result(outputs.get(ref, "{}"))

    with pytest.raises(RuntimeError, match="Invalid git ref"):
        build_changed_url_payload("bad-ref", "new", runner=fake_runner)


def test_changed_url_payload_trims_ref_whitespace() -> None:
    outputs = {
        "old": json.dumps({"/sdk/nodejs/": "a"}),
        "new": json.dumps({"/sdk/nodejs/": "b"}),
    }

    def fake_runner(cmd, capture_output, text, check):
        class Result:
            def __init__(self, stdout: str = "") -> None:
                self.stdout = stdout

        if cmd[:3] == ["git", "rev-parse", "--verify"]:
            return Result("ok")
        if cmd[:2] == ["git", "fetch"]:
            return Result("")
        ref = cmd[2].split(":", 1)[0]
        return Result(outputs[ref])

    payload = build_changed_url_payload(" old ", " new ", runner=fake_runner)

    assert payload["before"] == "old"
    assert payload["after"] == "new"


def test_track_requires_non_empty_changed_url_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "track_implementations_from_indexing.read_global_context",
        lambda key: json.dumps(
            {
                "before": "abc",
                "after": "def",
                "lastmod_path": "src/data/lastmod.json",
                "changed_count": 0,
                "changed_paths": [],
                "changed_urls": [],
            }
        ),
    )

    payload = load_payload(None)

    with pytest.raises(RuntimeError, match="Changed URL payload is empty"):
        changed_paths = payload.get("changed_paths", [])
        if not changed_paths:
            raise RuntimeError(
                "Changed URL payload is empty. "
                f"before={payload.get('before')!r} after={payload.get('after')!r} "
                f"lastmod_path={payload.get('lastmod_path')!r}"
            )
