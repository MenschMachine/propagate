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
    extract_issue_numbers_from_pr,
    gh_pr_for_commit,
    has_equivalent_pending_entry,
    load_payload,
    normalize_change,
    parse_issue_like_body,
    resolve_issue_metadata,
    select_best_pr_candidate,
    suggestion_type_from_metadata,
    url_matches_issue_page,
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
        "https://www.pdfdancer.com/sdk/java/",
        "https://www.pdfdancer.com/sdk/nodejs/",
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


def test_extract_issue_numbers_from_pr_uses_closing_and_body_refs() -> None:
    pr_data = {
        "closingIssuesReferences": [{"number": 12}],
        "body": "Implements #13 and relates to https://github.com/MenschMachine/pdfdancer-www/issues/14",
    }
    numbers = extract_issue_numbers_from_pr(pr_data)
    assert numbers == [12, 13, 14]


def test_url_matches_issue_page_supports_prefix_match() -> None:
    assert url_matches_issue_page("/sdk/python/", "/sdk/") == 2
    assert url_matches_issue_page("/sdk/python/", "/sdk/python/") == 3
    assert url_matches_issue_page("/sdk/python/", "/blog/") == 0


def test_select_best_pr_candidate_prefers_latest_merged_by_default() -> None:
    prs = [
        {
            "number": 100,
            "state": "CLOSED",
            "baseRefName": "main",
            "mergedAt": None,
            "updatedAt": "2026-04-10T12:00:00Z",
        },
        {
            "number": 121,
            "state": "MERGED",
            "baseRefName": "main",
            "mergedAt": "2026-04-10T11:00:00Z",
            "updatedAt": "2026-04-10T11:01:00Z",
        },
        {
            "number": 130,
            "state": "MERGED",
            "baseRefName": "main",
            "mergedAt": "2026-04-10T13:00:00Z",
            "updatedAt": "2026-04-10T13:01:00Z",
        },
    ]
    selected = select_best_pr_candidate(prs)
    assert selected is not None
    assert selected["number"] == 130


def test_select_best_pr_candidate_can_include_unmerged_for_testing() -> None:
    prs = [
        {
            "number": 121,
            "state": "MERGED",
            "baseRefName": "main",
            "mergedAt": "2026-04-10T05:07:14Z",
            "updatedAt": "2026-04-10T05:07:15Z",
        },
        {
            "number": 124,
            "state": "OPEN",
            "baseRefName": "main",
            "mergedAt": None,
            "updatedAt": "2026-04-10T07:30:00Z",
        },
    ]
    selected = select_best_pr_candidate(prs)
    assert selected is not None
    assert selected["number"] == 121

    selected_with_unmerged = select_best_pr_candidate(prs, consider_unmerged_prs=True)
    assert selected_with_unmerged is not None
    assert selected_with_unmerged["number"] == 124


def test_resolve_issue_metadata_reports_explicit_scope_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    pr_data = {
        "closingIssuesReferences": [{"number": 115}],
        "body": "",
    }

    monkeypatch.setattr(
        "track_implementations_from_indexing.gh_issue",
        lambda number: {
            "url": "https://github.com/MenschMachine/pdfdancer-www/issues/115",
            "body": (
                "**Page:** `/sdk/fastapi/`\n"
                "**Action:** `new-page`\n"
                "**Diagnosis:** `technical`\n"
            ),
        },
    )

    metadata, has_explicit_scope = resolve_issue_metadata(pr_data, "/sdk/python/")

    assert metadata is None
    assert has_explicit_scope is True


def test_has_equivalent_pending_entry_matches_same_event_identity() -> None:
    entries = [
        {
            "url": "/sdk/fastapi/",
            "date_implemented": "2026-04-10",
            "suggestion_source": "https://github.com/MenschMachine/pdfdancer-www/issues/115",
            "change": "Create a dedicated page for /sdk/fastapi/",
            "status": "pending",
        }
    ]
    candidate = {
        "url": "/sdk/fastapi/",
        "date_implemented": "2026-04-10",
        "suggestion_source": "https://github.com/MenschMachine/pdfdancer-www/issues/115",
        "change": "Create a dedicated page for /sdk/fastapi/",
        "status": "pending",
    }
    assert has_equivalent_pending_entry(entries, candidate) is True


def test_has_equivalent_pending_entry_allows_new_change_on_same_url() -> None:
    entries = [
        {
            "url": "/sdk/fastapi/",
            "date_implemented": "2026-04-09",
            "suggestion_source": "https://github.com/MenschMachine/pdfdancer-www/issues/115",
            "change": "Create a dedicated page for /sdk/fastapi/",
            "status": "pending",
        }
    ]
    candidate = {
        "url": "/sdk/fastapi/",
        "date_implemented": "2026-04-10",
        "suggestion_source": "https://github.com/MenschMachine/pdfdancer-www/issues/115",
        "change": "Refresh page content for /sdk/fastapi/",
        "status": "pending",
    }
    assert has_equivalent_pending_entry(entries, candidate) is False


def test_pr_lookup_logs_no_matches_when_rest_and_graphql_succeed_with_empty_results(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("track_implementations_from_indexing.LOOKUP_RETRY_DELAYS_SECONDS", ())
    monkeypatch.setattr(
        "track_implementations_from_indexing.gh_pr_numbers_for_commit_rest",
        lambda commit_sha: ([], None),
    )
    monkeypatch.setattr(
        "track_implementations_from_indexing.gh_pr_numbers_for_commit_graphql",
        lambda commit_sha: ([], None),
    )
    monkeypatch.setattr(
        "track_implementations_from_indexing.gh_pr_number_from_merge_commit_message",
        lambda commit_sha: (None, None),
    )

    with caplog.at_level("INFO"):
        pr_data = gh_pr_for_commit("abc123")

    assert pr_data is None
    assert "REST returned 0 associated PR(s)" in caplog.text
    assert "GraphQL returned 0 associated PR(s)" in caplog.text
    assert "no associated PR found after retries and fallback" in caplog.text
    assert "REST request failed" not in caplog.text


def test_pr_lookup_logs_api_failures_separately_from_no_matches(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("track_implementations_from_indexing.LOOKUP_RETRY_DELAYS_SECONDS", ())
    monkeypatch.setattr(
        "track_implementations_from_indexing.gh_pr_numbers_for_commit_rest",
        lambda commit_sha: ([], "exit=1 stderr=HTTP 403"),
    )
    monkeypatch.setattr(
        "track_implementations_from_indexing.gh_pr_numbers_for_commit_graphql",
        lambda commit_sha: ([], "exit=1 stderr=HTTP 403"),
    )
    monkeypatch.setattr(
        "track_implementations_from_indexing.gh_pr_number_from_merge_commit_message",
        lambda commit_sha: (None, "exit=1 stderr=HTTP 403"),
    )

    with caplog.at_level("INFO"):
        pr_data = gh_pr_for_commit("def456")

    assert pr_data is None
    assert "REST request failed" in caplog.text
    assert "GraphQL request failed" in caplog.text
    assert "merge-commit fallback lookup failed" in caplog.text
    assert "unable to resolve PR due to GitHub API errors" in caplog.text


def test_pr_lookup_uses_merge_commit_message_fallback_when_association_is_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("track_implementations_from_indexing.LOOKUP_RETRY_DELAYS_SECONDS", ())
    monkeypatch.setattr(
        "track_implementations_from_indexing.gh_pr_numbers_for_commit_rest",
        lambda commit_sha: ([], None),
    )
    monkeypatch.setattr(
        "track_implementations_from_indexing.gh_pr_numbers_for_commit_graphql",
        lambda commit_sha: ([], None),
    )
    monkeypatch.setattr(
        "track_implementations_from_indexing.gh_pr_number_from_merge_commit_message",
        lambda commit_sha: (135, None),
    )
    monkeypatch.setattr(
        "track_implementations_from_indexing.gh_pr_details",
        lambda number: {
            "number": number,
            "state": "MERGED",
            "baseRefName": "main",
            "mergedAt": "2026-04-11T06:49:45Z",
            "updatedAt": "2026-04-11T06:49:45Z",
            "url": "https://github.com/MenschMachine/pdfdancer-www/pull/135",
            "body": "",
            "title": "Issue/126",
            "closingIssuesReferences": [],
        },
    )

    with caplog.at_level("INFO"):
        pr_data = gh_pr_for_commit("74c773e24ab73fb8f5a60024368224e235c6a4d2")

    assert pr_data is not None
    assert pr_data["number"] == 135
    assert "inferred PR #135 from merge commit message fallback" in caplog.text
