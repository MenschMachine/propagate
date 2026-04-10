#!/usr/bin/env python3
"""Append SEO implementation ledger entries from the request-indexing pipeline."""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml
from evaluate_implementations import (
    aggregate_by_page,
    list_data_dirs,
    load_gsc_data,
    load_page_content_for_url,
)

log = logging.getLogger(__name__)

LEDGER_PATH = Path("data/feedback/implementations.yaml")
DATA_DIR = Path("data")
WWW_REPO = "MenschMachine/pdfdancer-www"

MULTIPLIER_BY_TYPE = {
    "meta": 2,
    "content-edit": 3,
    "new-content": 4,
    "technical": 2,
}


def run_json(cmd: list[str], *, check: bool = True, default=None):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=check)
    except subprocess.CalledProcessError:
        return default
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return default


def read_global_context(key: str) -> str:
    result = subprocess.run(
        ["propagate", "context", "get", "--global", key],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def load_payload(payload_json: str | None) -> dict:
    if payload_json:
        return json.loads(payload_json)
    raw = read_global_context(":changed-url-payload")
    return json.loads(raw)


def load_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    data = yaml.safe_load(text)
    return data if isinstance(data, list) else []


def save_ledger(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(entries, sort_keys=False, default_flow_style=False), encoding="utf-8")


def gh_pr_for_commit(commit_sha: str) -> dict | None:
    prs = run_json(
        ["gh", "api", f"repos/{WWW_REPO}/commits/{commit_sha}/pulls"],
        default=[],
    )
    if not prs:
        return None
    pr = prs[0]
    return run_json(
        [
            "gh",
            "pr",
            "view",
            str(pr["number"]),
            "--repo",
            WWW_REPO,
            "--json",
            "body,url,number,title,closingIssuesReferences",
        ],
        default=None,
    )


def gh_issue(number: int) -> dict | None:
    return run_json(
        [
            "gh",
            "issue",
            "view",
            str(number),
            "--repo",
            WWW_REPO,
            "--json",
            "body,url,number,title",
        ],
        default=None,
    )


def gh_compare_files(before_sha: str, after_sha: str) -> list[dict]:
    data = run_json(
        ["gh", "api", f"repos/{WWW_REPO}/compare/{before_sha}...{after_sha}"],
        default={},
    )
    files = data.get("files", [])
    return files if isinstance(files, list) else []


def parse_issue_like_body(body: str) -> dict:
    page_match = re.search(r"\*\*Page:\*\*\s+`([^`]+)`", body)
    action_match = re.search(r"\*\*Action:\*\*\s+`([^`]+)`", body)
    diagnosis_match = re.search(r"\*\*Diagnosis:\*\*\s+`([^`]+)`", body)
    change_type_match = re.search(r"\*\*Change type:\*\*\s*`?([^`\n]+?)`?\s*(?:\n|$)", body)
    must_change_match = re.search(r"\*\*Must change:\*\*\s*(.+)", body)

    return {
        "page": page_match.group(1).strip() if page_match else None,
        "action": action_match.group(1).strip() if action_match else None,
        "diagnosis": diagnosis_match.group(1).strip() if diagnosis_match else None,
        "change_type": change_type_match.group(1).strip() if change_type_match else None,
        "must_change": must_change_match.group(1).strip() if must_change_match else None,
    }


def suggestion_type_from_metadata(action: str | None, diagnosis: str | None) -> str:
    normalized_action = (action or "").strip().lower()
    normalized_diagnosis = (diagnosis or "").strip().lower()
    if normalized_diagnosis == "meta":
        return "meta"
    if normalized_diagnosis == "technical":
        return "technical"
    if normalized_action == "new-page" or normalized_diagnosis == "new-page-opportunity":
        return "new-content"
    return "content-edit"


def normalize_change(action: str | None, must_change: str | None, url_path: str) -> str:
    if must_change:
        text = re.sub(r"\s+", " ", must_change).strip()
        return text[:240]
    normalized_action = (action or "").strip().lower()
    if normalized_action == "new-page":
        return f"Create a dedicated page for {url_path}"
    if normalized_action == "rewrite":
        return f"Rewrite page content for {url_path}"
    if normalized_action == "refresh":
        return f"Refresh page content for {url_path}"
    if normalized_action == "expand":
        return f"Expand page content for {url_path}"
    if normalized_action == "trim":
        return f"Trim page content for {url_path}"
    return f"Update page content for {url_path}"


def resolve_issue_metadata(pr_data: dict | None, url_path: str) -> dict | None:
    if not pr_data:
        return None
    issues = pr_data.get("closingIssuesReferences") or []
    for issue_ref in issues:
        issue_number = issue_ref.get("number")
        if not issue_number:
            continue
        issue = gh_issue(issue_number)
        if not issue:
            continue
        parsed = parse_issue_like_body(issue.get("body", ""))
        if parsed.get("page") != url_path:
            continue
        return {
            "source": issue["url"],
            "action": parsed.get("action"),
            "diagnosis": parsed.get("diagnosis"),
            "change": normalize_change(parsed.get("change_type") or parsed.get("action"), parsed.get("must_change"), url_path),
        }
    return None


def resolve_pr_metadata(pr_data: dict | None, url_path: str) -> dict | None:
    if not pr_data:
        return None
    parsed = parse_issue_like_body(pr_data.get("body", ""))
    if parsed.get("page") and parsed["page"] != url_path:
        return None
    action = parsed.get("change_type") or parsed.get("action")
    if not action and not parsed.get("diagnosis"):
        return None
    return {
        "source": pr_data["url"],
        "action": action,
        "diagnosis": parsed.get("diagnosis"),
        "change": normalize_change(action, parsed.get("must_change"), url_path),
    }


def resolve_git_metadata(compare_files: list[dict], url_path: str, commit_sha: str) -> dict:
    slug = url_path.strip("/") or "index"
    matched_files = [f for f in compare_files if slug in f.get("filename", "")]
    status = matched_files[0].get("status", "") if matched_files else ""
    patch = "\n".join(f.get("patch", "") for f in matched_files)
    lowered_patch = patch.lower()
    if status == "added":
        action = "new-page"
        diagnosis = "new-page-opportunity"
    elif "title" in lowered_patch or "description" in lowered_patch or "meta" in lowered_patch:
        action = "rewrite"
        diagnosis = "meta"
    else:
        action = "refresh"
        diagnosis = "content-quality"
    return {
        "source": f"git-reconstructed:{commit_sha}",
        "action": action,
        "diagnosis": diagnosis,
        "change": normalize_change(action, None, url_path),
    }


def aggregate_baseline(url_path: str, data_dir: Path, implemented_on: date) -> dict:
    dated_dirs = [item for item in list_data_dirs(data_dir) if item[0] <= implemented_on]
    selected = dated_dirs[-4:]
    weeks = []
    for dir_date, dir_path in selected:
        gsc_data = load_gsc_data(dir_path / "gsc.json")
        page_data = aggregate_by_page(gsc_data or {})
        metrics = page_data.get(url_path, {})
        start = (gsc_data or {}).get("start_date", dir_date.isoformat())
        end = (gsc_data or {}).get("end_date", dir_date.isoformat())
        weeks.append(
            {
                "period": f"{start} to {end}",
                "impressions": int(metrics.get("impressions", 0)),
                "clicks": int(metrics.get("clicks", 0)),
                "ctr": round(float(metrics.get("ctr", 0.0)), 2),
                "position": round(float(metrics.get("position", 0.0)), 2),
            }
        )
    if not weeks:
        weeks = [
            {"period": implemented_on.isoformat(), "impressions": 0, "clicks": 0, "ctr": 0.0, "position": 0.0}
        ]
    count = len(weeks)
    averages = {
        "impressions": round(sum(item["impressions"] for item in weeks) / count, 2),
        "clicks": round(sum(item["clicks"] for item in weeks) / count, 2),
        "ctr": round(sum(item["ctr"] for item in weeks) / count, 2),
        "position": round(sum(item["position"] for item in weeks) / count, 2),
    }
    return {"weeks": weeks, "averages": averages}


def snapshot_indexed_content(url_path: str, suggestion_type: str, data_dir: Path) -> dict | None:
    if suggestion_type != "meta":
        return None
    page_content = load_page_content_for_url(data_dir, url_path)
    if not page_content:
        return None
    title = page_content.get("title")
    description = page_content.get("meta_description")
    if not title and not description:
        return None
    return {"title": title or "", "description": description or ""}


def has_pending_entry(entries: list[dict], url_path: str) -> bool:
    return any(entry.get("url") == url_path and entry.get("status") == "pending" for entry in entries)


def build_entry(url_path: str, metadata: dict, implemented_on: date, data_dir: Path) -> dict:
    suggestion_type = suggestion_type_from_metadata(metadata.get("action"), metadata.get("diagnosis"))
    baseline = aggregate_baseline(url_path, data_dir, implemented_on)
    multiplier = MULTIPLIER_BY_TYPE[suggestion_type]
    avg_impressions = baseline["averages"]["impressions"]
    entry = {
        "url": url_path,
        "suggestion_type": suggestion_type,
        "change": metadata["change"],
        "date_implemented": implemented_on.isoformat(),
        "suggestion_source": metadata["source"],
        "min_impressions_for_eval": int(math.ceil(avg_impressions * multiplier)),
        "baseline": baseline,
        "status": "pending",
        "evaluation": None,
    }
    snapshot = snapshot_indexed_content(url_path, suggestion_type, data_dir)
    if snapshot:
        entry["indexed_at_implementation"] = snapshot
    return entry


def main() -> str:
    parser = argparse.ArgumentParser(description="Track SEO implementations from request-indexing")
    parser.add_argument("--payload-json", help="Precomputed changed-url payload")
    parser.add_argument("--date", help="Implementation date override (YYYY-MM-DD)")
    parser.add_argument("--ledger-path", default=str(LEDGER_PATH))
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    args = parser.parse_args()

    implemented_on = date.fromisoformat(args.date) if args.date else date.today()
    payload = load_payload(args.payload_json)
    changed_paths = payload.get("changed_paths", [])
    ledger_path = Path(args.ledger_path)
    data_dir = Path(args.data_dir)
    entries = load_ledger(ledger_path)

    pr_data = gh_pr_for_commit(payload["after"])
    compare_files = gh_compare_files(payload["before"], payload["after"])

    appended = []
    skipped = []
    for url_path in changed_paths:
        if has_pending_entry(entries, url_path):
            skipped.append({"url": url_path, "reason": "pending entry already exists"})
            continue
        metadata = resolve_issue_metadata(pr_data, url_path)
        if metadata is None:
            metadata = resolve_pr_metadata(pr_data, url_path)
        if metadata is None:
            metadata = resolve_git_metadata(compare_files, url_path, payload["after"])
        entry = build_entry(url_path, metadata, implemented_on, data_dir)
        entries.append(entry)
        appended.append(
            {
                "url": url_path,
                "suggestion_type": entry["suggestion_type"],
                "suggestion_source": entry["suggestion_source"],
            }
        )

    if appended:
        save_ledger(ledger_path, entries)

    result = json.dumps({"appended": appended, "skipped": skipped})
    print(result)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
    main()
