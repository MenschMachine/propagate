"""Tests for the evaluate_implementations script."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "config" / "scripts"))

from evaluate_implementations import (  # noqa: E402
    aggregate_by_page,
    check_deployment_status,
    check_gates,
    classify_outcome,
    compute_baseline_std,
    evaluate_entry,
    extract_path,
    load_ledger,
    load_page_content_for_url,
    main,
    save_ledger,
)


def make_gsc_json(page_path: str, impressions: int = 100, clicks: int = 5,
                   position: float = 10.0, start_date: str = "2026-03-01",
                   end_date: str = "2026-03-07", domain: str = "https://www.pdfdancer.com"):
    """Build a minimal GSC JSON structure."""
    ctr = (clicks / impressions * 100) if impressions > 0 else 0
    return {
        "site_url": "sc-domain:pdfdancer.com",
        "start_date": start_date,
        "end_date": end_date,
        "query_page": [
            {
                "query": "test query",
                "page": f"{domain}{page_path}",
                "clicks": clicks,
                "impressions": impressions,
                "ctr": round(ctr, 2),
                "position": position,
            }
        ],
    }


def make_entry(url: str = "/sdk/nodejs/", suggestion_type: str = "meta",
               date_implemented: str = "2026-03-01",
               min_impressions: int = 200, baseline_weeks: list | None = None,
               baseline_avgs: dict | None = None):
    """Build a minimal ledger entry."""
    if baseline_weeks is None:
        baseline_weeks = [
            {"period": "2026-02-10 to 2026-02-16", "impressions": 100, "clicks": 1, "ctr": 1.0, "position": 10.0},
            {"period": "2026-02-17 to 2026-02-23", "impressions": 110, "clicks": 1, "ctr": 0.91, "position": 10.5},
            {"period": "2026-02-24 to 2026-03-02", "impressions": 105, "clicks": 2, "ctr": 1.9, "position": 10.2},
            {"period": "2026-03-03 to 2026-03-09", "impressions": 95, "clicks": 1, "ctr": 1.05, "position": 11.0},
        ]
    if baseline_avgs is None:
        baseline_avgs = {
            "impressions": 102.5,
            "clicks": 1.25,
            "ctr": 1.22,
            "position": 10.43,
        }
    return {
        "url": url,
        "suggestion_type": suggestion_type,
        "change": "Test change",
        "date_implemented": date_implemented,
        "suggestion_source": "test",
        "min_impressions_for_eval": min_impressions,
        "baseline": {
            "weeks": baseline_weeks,
            "averages": baseline_avgs,
        },
        "status": "pending",
        "evaluation": None,
    }


def setup_data_dir(tmp_path: Path, date_str: str, gsc_data: dict) -> Path:
    """Create a data/YYYY-MM-DD/gsc.json structure."""
    d = tmp_path / "data" / date_str
    d.mkdir(parents=True, exist_ok=True)
    (d / "gsc.json").write_text(json.dumps(gsc_data), encoding="utf-8")
    return d


# --- extract_path ---

def test_extract_path_full_url():
    assert extract_path("https://www.pdfdancer.com/sdk/nodejs/") == "/sdk/nodejs/"


def test_extract_path_already_path():
    assert extract_path("/sdk/nodejs/") == "/sdk/nodejs/"


def test_extract_path_no_path():
    assert extract_path("https://example.com") == "/"


# --- aggregate_by_page ---

def test_aggregate_by_page_sums_rows():
    gsc_data = {
        "query_page": [
            {"query": "q1", "page": "https://www.pdfdancer.com/sdk/nodejs/",
             "clicks": 2, "impressions": 100, "ctr": 2.0, "position": 8.0},
            {"query": "q2", "page": "https://www.pdfdancer.com/sdk/nodejs/",
             "clicks": 3, "impressions": 50, "ctr": 6.0, "position": 12.0},
        ],
    }
    result = aggregate_by_page(gsc_data)
    assert "/sdk/nodejs/" in result
    page = result["/sdk/nodejs/"]
    assert page["impressions"] == 150
    assert page["clicks"] == 5
    # Weighted avg position: (8*100 + 12*50) / 150 = 1400/150 ≈ 9.33
    assert round(page["position"], 2) == 9.33
    # CTR: 5/150 * 100 ≈ 3.33
    assert round(page["ctr"], 2) == 3.33


def test_aggregate_by_page_empty():
    assert aggregate_by_page({"query_page": []}) == {}
    assert aggregate_by_page({}) == {}


# --- compute_baseline_std ---

def test_compute_baseline_std():
    entry = make_entry()
    std = compute_baseline_std(entry, "ctr")
    assert std > 0


def test_compute_baseline_std_single_week():
    entry = make_entry(baseline_weeks=[
        {"period": "w1", "impressions": 100, "clicks": 1, "ctr": 1.0, "position": 10.0},
    ])
    assert compute_baseline_std(entry, "ctr") == 0.0


# --- check_gates ---

def test_gates_pending_missing_min_impressions():
    entry = make_entry(date_implemented="2026-03-01")
    del entry["min_impressions_for_eval"]
    today = date(2026, 3, 20)
    assert check_gates(entry, today, 9999) == "pending"


def test_gates_pending_calendar_floor():
    entry = make_entry(date_implemented="2026-03-10")
    today = date(2026, 3, 20)  # 10 days, below 14-day floor
    assert check_gates(entry, today, 0) == "pending"


def test_gates_pending_volume():
    entry = make_entry(date_implemented="2026-03-01", min_impressions=500)
    today = date(2026, 3, 20)
    assert check_gates(entry, today, 100) == "pending"


def test_gates_ready():
    entry = make_entry(date_implemented="2026-03-01", min_impressions=200)
    today = date(2026, 3, 20)
    assert check_gates(entry, today, 250) == "ready"


def test_gates_ceiling():
    entry = make_entry(date_implemented="2025-12-01", min_impressions=99999)
    today = date(2026, 3, 20)  # >90 days
    assert check_gates(entry, today, 0) == "ceiling"


# --- classify_outcome ---

def test_classify_improved():
    entry = make_entry(
        suggestion_type="meta",
        baseline_avgs={"ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
        baseline_weeks=[
            {"period": "w1", "ctr": 0.9, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w2", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w3", "ctr": 1.1, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w4", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
        ],
    )
    post_weeks = [
        {"ctr": 3.0, "impressions": 120, "clicks": 4, "position": 9.0},
        {"ctr": 3.5, "impressions": 130, "clicks": 5, "position": 8.5},
    ]
    state, reason = classify_outcome(entry, post_weeks)
    assert state == "improved"
    assert "ctr" in reason


def test_classify_declined():
    entry = make_entry(
        suggestion_type="meta",
        baseline_avgs={"ctr": 3.0, "impressions": 100, "clicks": 3, "position": 10.0},
        baseline_weeks=[
            {"period": "w1", "ctr": 2.9, "impressions": 100, "clicks": 3, "position": 10.0},
            {"period": "w2", "ctr": 3.0, "impressions": 100, "clicks": 3, "position": 10.0},
            {"period": "w3", "ctr": 3.1, "impressions": 100, "clicks": 3, "position": 10.0},
            {"period": "w4", "ctr": 3.0, "impressions": 100, "clicks": 3, "position": 10.0},
        ],
    )
    post_weeks = [
        {"ctr": 0.5, "impressions": 90, "clicks": 0, "position": 12.0},
        {"ctr": 0.3, "impressions": 80, "clicks": 0, "position": 13.0},
    ]
    state, reason = classify_outcome(entry, post_weeks)
    assert state == "declined"


def test_classify_inconclusive():
    entry = make_entry(
        suggestion_type="meta",
        baseline_avgs={"ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
        baseline_weeks=[
            {"period": "w1", "ctr": 0.5, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w2", "ctr": 1.5, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w3", "ctr": 0.8, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w4", "ctr": 1.2, "impressions": 100, "clicks": 1, "position": 10.0},
        ],
    )
    # Post change is within noise band (std dev ≈ 0.42, threshold ≈ 0.84)
    post_weeks = [
        {"ctr": 1.5, "impressions": 100, "clicks": 2, "position": 10.0},
        {"ctr": 1.3, "impressions": 100, "clicks": 1, "position": 10.0},
    ]
    state, reason = classify_outcome(entry, post_weeks)
    assert state == "inconclusive"


def test_classify_no_change():
    entry = make_entry(
        suggestion_type="meta",
        baseline_avgs={"ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
        baseline_weeks=[
            {"period": "w1", "ctr": 0.9, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w2", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w3", "ctr": 1.1, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w4", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
        ],
    )
    post_weeks = [
        {"ctr": 1.001, "impressions": 100, "clicks": 1, "position": 10.0},
        {"ctr": 0.999, "impressions": 100, "clicks": 1, "position": 10.0},
    ]
    state, reason = classify_outcome(entry, post_weeks)
    assert state == "no_change"


def test_classify_zero_std_dev():
    entry = make_entry(
        suggestion_type="meta",
        baseline_avgs={"ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
        baseline_weeks=[
            {"period": "w1", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w2", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w3", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
            {"period": "w4", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
        ],
    )
    post_weeks = [
        {"ctr": 2.5, "impressions": 100, "clicks": 3, "position": 10.0},
    ]
    state, reason = classify_outcome(entry, post_weeks)
    assert state == "improved"
    assert "zero variance" in reason


def test_classify_position_lower_is_better():
    entry = make_entry(
        suggestion_type="technical",
        baseline_avgs={"ctr": 1.0, "impressions": 100, "clicks": 1, "position": 15.0},
        baseline_weeks=[
            {"period": "w1", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 15.0},
            {"period": "w2", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 15.2},
            {"period": "w3", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 14.8},
            {"period": "w4", "ctr": 1.0, "impressions": 100, "clicks": 1, "position": 15.0},
        ],
    )
    # Position improved (went down from 15 to 8)
    post_weeks = [
        {"ctr": 2.0, "impressions": 120, "clicks": 2, "position": 8.0},
        {"ctr": 2.5, "impressions": 130, "clicks": 3, "position": 7.5},
    ]
    state, reason = classify_outcome(entry, post_weeks)
    assert state == "improved"


# --- evaluate_entry ---

def test_evaluate_entry_ceiling(tmp_path):
    entry = make_entry(date_implemented="2025-12-01")
    today = date(2026, 3, 20)
    result = evaluate_entry(entry, today, [])
    assert result["status"] == "evaluated"
    assert result["evaluation"]["state"] == "inconclusive"
    assert "insufficient_volume" in result["evaluation"]["reason"]


def test_evaluate_entry_ready(tmp_path):
    entry = make_entry(date_implemented="2026-03-01", min_impressions=50)
    today = date(2026, 3, 20)
    setup_data_dir(tmp_path, "2026-03-10",
                   make_gsc_json("/sdk/nodejs/", impressions=200, clicks=10,
                                 start_date="2026-03-04", end_date="2026-03-10"))
    data_dirs = [(date(2026, 3, 10), tmp_path / "data" / "2026-03-10")]
    result = evaluate_entry(entry, today, data_dirs)
    assert result["status"] == "evaluated"
    assert result["evaluation"]["state"] in ("improved", "declined", "inconclusive", "no_change")


# --- ledger round-trip ---

def test_ledger_round_trip(tmp_path):
    ledger_path = tmp_path / "implementations.yaml"
    entries = [make_entry(), make_entry(url="/other/")]
    save_ledger(ledger_path, entries)
    loaded = load_ledger(ledger_path)
    assert len(loaded) == 2
    assert loaded[0]["url"] == "/sdk/nodejs/"
    assert loaded[1]["url"] == "/other/"


def test_load_empty_ledger(tmp_path):
    ledger_path = tmp_path / "implementations.yaml"
    ledger_path.write_text("", encoding="utf-8")
    assert load_ledger(ledger_path) == []


def test_load_missing_ledger(tmp_path):
    ledger_path = tmp_path / "nonexistent.yaml"
    assert load_ledger(ledger_path) == []


# --- main integration ---

def test_main_empty_ledger(tmp_path):
    ledger_path = tmp_path / "implementations.yaml"
    result = main(today=date(2026, 3, 20), ledger_path=ledger_path, data_dir=tmp_path / "data")
    parsed = json.loads(result)
    assert parsed["newly_evaluated"] == []
    assert parsed["pending"] == []


def test_main_evaluates_mature_entry(tmp_path):
    ledger_path = tmp_path / "data" / "feedback" / "implementations.yaml"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    entry = make_entry(
        date_implemented="2026-03-01",
        min_impressions=50,
        baseline_avgs={"ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
    )
    save_ledger(ledger_path, [entry])

    # Create post-change GSC data with high CTR (improved)
    setup_data_dir(tmp_path, "2026-03-10",
                   make_gsc_json("/sdk/nodejs/", impressions=200, clicks=20,
                                 start_date="2026-03-04", end_date="2026-03-10"))

    result = main(today=date(2026, 3, 20), ledger_path=ledger_path, data_dir=tmp_path / "data")
    parsed = json.loads(result)
    assert len(parsed["newly_evaluated"]) == 1
    assert parsed["newly_evaluated"][0]["url"] == "/sdk/nodejs/"

    # Verify ledger was updated
    updated = load_ledger(ledger_path)
    assert updated[0]["status"] == "evaluated"


def test_main_skips_already_evaluated(tmp_path):
    ledger_path = tmp_path / "implementations.yaml"
    entry = make_entry()
    entry["status"] = "evaluated"
    entry["evaluation"] = {"date": "2026-03-15", "state": "improved", "reason": "test"}
    save_ledger(ledger_path, [entry])

    result = main(today=date(2026, 3, 20), ledger_path=ledger_path, data_dir=tmp_path / "data")
    parsed = json.loads(result)
    assert parsed["newly_evaluated"] == []


def test_main_no_gsc_data_post_implementation(tmp_path):
    ledger_path = tmp_path / "implementations.yaml"
    entry = make_entry(date_implemented="2026-03-01", min_impressions=50)
    save_ledger(ledger_path, [entry])

    # No data dirs at all
    result = main(today=date(2026, 3, 20), ledger_path=ledger_path, data_dir=tmp_path / "data")
    parsed = json.loads(result)
    # Should remain pending (no volume)
    assert parsed["newly_evaluated"] == []
    assert len(parsed["pending"]) == 1


# --- load_page_content_for_url ---

def setup_page_content(tmp_path, date_str, url_path, content):
    """Create a data/YYYY-MM-DD/pages/<filename>.json structure."""
    pages_dir = tmp_path / "data" / date_str / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    # Match fetch_page_content.py's url_to_filename: collapse non-alphanumeric to _
    filename = re.sub(r"[^a-zA-Z0-9]+", "_", url_path.strip("/")) + ".json"
    (pages_dir / filename).write_text(json.dumps(content), encoding="utf-8")
    return pages_dir / filename


def test_load_page_content_for_url(tmp_path):
    content = {
        "url": "https://www.pdfdancer.com/sdk/nodejs/",
        "title": "Node.js PDF SDK",
        "meta_description": "Build PDF apps with Node.js",
    }
    setup_page_content(tmp_path, "2026-03-16", "/sdk/nodejs/", content)
    data_dir = tmp_path / "data"
    result = load_page_content_for_url(data_dir, "/sdk/nodejs/")
    assert result is not None
    assert result["title"] == "Node.js PDF SDK"


def test_load_page_content_for_url_missing(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    result = load_page_content_for_url(data_dir, "/nonexistent/page/")
    assert result is None


# --- check_deployment_status ---

def test_deployment_confirmed_title_changed():
    entry = make_entry(suggestion_type="meta")
    entry["indexed_at_implementation"] = {
        "title": "Old Title Before Change",
        "description": "Old description",
    }
    page_content = {
        "title": "New Better Title",
        "meta_description": "Old description",
    }
    result = check_deployment_status(entry, page_content)
    assert result["status"] == "confirmed_indexed"
    assert "title" in result["detail"]


def test_deployment_confirmed_description_changed():
    entry = make_entry(suggestion_type="meta")
    entry["indexed_at_implementation"] = {
        "title": "Same Title",
        "description": "Old description",
    }
    page_content = {
        "title": "Same Title",
        "meta_description": "New description",
    }
    result = check_deployment_status(entry, page_content)
    assert result["status"] == "confirmed_indexed"
    assert "description" in result["detail"]


def test_deployment_not_indexed():
    entry = make_entry(suggestion_type="meta")
    entry["indexed_at_implementation"] = {
        "title": "Old Title Before Change",
        "description": "Old description",
    }
    page_content = {
        "title": "Old Title Before Change",
        "meta_description": "Old description",
    }
    result = check_deployment_status(entry, page_content)
    assert result["status"] == "not_yet_indexed"


def test_deployment_unknown_no_snapshot():
    entry = make_entry(suggestion_type="meta")
    # No indexed_at_implementation field
    page_content = {
        "title": "Some Title",
        "meta_description": "Some description",
    }
    result = check_deployment_status(entry, page_content)
    assert result["status"] == "unknown"


def test_deployment_unknown_empty_page_content():
    entry = make_entry(suggestion_type="meta")
    entry["indexed_at_implementation"] = {
        "title": "Old Title",
        "description": "Old desc",
    }
    page_content = {
        "title": "",
        "meta_description": "",
    }
    result = check_deployment_status(entry, page_content)
    assert result["status"] == "unknown"


def test_deployment_non_meta():
    entry = make_entry(suggestion_type="content-edit")
    entry["indexed_at_implementation"] = {
        "title": "Some Title",
        "description": "Some description",
    }
    page_content = {
        "title": "Some Title",
        "meta_description": "Some description",
    }
    result = check_deployment_status(entry, page_content)
    assert result["status"] == "unknown"


# --- summary includes deployment_status ---

def test_summary_includes_deployment_status(tmp_path):
    ledger_path = tmp_path / "data" / "feedback" / "implementations.yaml"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    # Use recent date + high min_impressions so it stays pending
    entry = make_entry(
        date_implemented="2026-03-10",
        min_impressions=99999,
        suggestion_type="meta",
        baseline_avgs={"ctr": 1.0, "impressions": 100, "clicks": 1, "position": 10.0},
    )
    entry["indexed_at_implementation"] = {
        "title": "Old Title",
        "description": "Old desc",
    }
    save_ledger(ledger_path, [entry])

    # Create page content showing the title changed
    setup_page_content(tmp_path, "2026-03-16", "/sdk/nodejs/", {
        "url": "https://www.pdfdancer.com/sdk/nodejs/",
        "title": "New Title After Implementation",
        "meta_description": "New desc",
    })

    result = main(today=date(2026, 3, 27), ledger_path=ledger_path, data_dir=tmp_path / "data")
    parsed = json.loads(result)
    assert "deployment_status" in parsed
    assert len(parsed["deployment_status"]) == 1
    assert parsed["deployment_status"][0]["status"] == "confirmed_indexed"
