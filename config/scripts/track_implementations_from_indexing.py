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


def _pr_rank_key(pr: dict) -> tuple[str, str, int]:
    merged_at = pr.get("mergedAt") or ""
    updated_at = pr.get("updatedAt") or ""
    number = int(pr.get("number") or 0)
    return (merged_at, updated_at, number)


def select_best_pr_candidate(prs: list[dict], *, consider_unmerged_prs: bool = False) -> dict | None:
    if not prs:
        return None
    filtered = prs
    if not consider_unmerged_prs:
        merged_only = [pr for pr in prs if pr.get("mergedAt")]
        if merged_only:
            filtered = merged_only
        return max(filtered, key=_pr_rank_key)

    def latest_key(pr: dict) -> tuple[str, int]:
        return (pr.get("updatedAt") or "", int(pr.get("number") or 0))

    return max(filtered, key=latest_key)


def gh_pr_details(number: int) -> dict | None:
    return run_json(
        [
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            WWW_REPO,
            "--json",
            "body,url,number,title,closingIssuesReferences,mergedAt,updatedAt,state,baseRefName",
        ],
        default=None,
    )


def gh_pr_for_commit(commit_sha: str, *, consider_unmerged_prs: bool = False) -> dict | None:
    prs = run_json(
        ["gh", "api", f"repos/{WWW_REPO}/commits/{commit_sha}/pulls"],
        default=[],
    )
    if not prs:
        return None
    candidates = []
    for pr in prs:
        number = pr.get("number")
        if not isinstance(number, int):
            continue
        details = gh_pr_details(number)
        if details is not None:
            candidates.append(details)
    if not candidates:
        return None
    log.info(
        "PR lookup for commit %s: candidate numbers=%s",
        commit_sha,
        [c.get("number") for c in candidates],
    )
    for candidate in candidates:
        log.info(
            "PR candidate #%s (state=%s mergedAt=%s base=%s updatedAt=%s)",
            candidate.get("number"),
            candidate.get("state"),
            candidate.get("mergedAt"),
            candidate.get("baseRefName"),
            candidate.get("updatedAt"),
        )
    selected = select_best_pr_candidate(candidates, consider_unmerged_prs=consider_unmerged_prs)
    if selected is not None:
        log.info(
            "PR lookup for commit %s: selected PR #%s (state=%s mergedAt=%s base=%s updatedAt=%s consider_unmerged_prs=%s)",
            commit_sha,
            selected.get("number"),
            selected.get("state"),
            selected.get("mergedAt"),
            selected.get("baseRefName"),
            selected.get("updatedAt"),
            consider_unmerged_prs,
        )
    return selected


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


def normalize_path(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith("/"):
        value = f"/{value}"
    if value != "/" and value.endswith("/"):
        value = value[:-1]
    return value


def url_matches_issue_page(url_path: str, issue_page: str | None) -> int:
    """Return a match score: 0=no match, 2=prefix match, 3=exact match."""
    normalized_url = normalize_path(url_path)
    normalized_issue = normalize_path(issue_page)
    if not normalized_url or not normalized_issue:
        return 0
    if normalized_url == normalized_issue:
        return 3
    if normalized_issue != "/" and normalized_url.startswith(f"{normalized_issue}/"):
        return 2
    return 0


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


def extract_issue_numbers_from_pr(pr_data: dict | None) -> list[int]:
    if not pr_data:
        return []
    numbers: set[int] = set()
    for issue_ref in pr_data.get("closingIssuesReferences") or []:
        number = issue_ref.get("number")
        if isinstance(number, int):
            numbers.add(number)

    body = pr_data.get("body") or ""
    for match in re.finditer(r"(?<![A-Za-z0-9_])#(\d+)\b", body):
        numbers.add(int(match.group(1)))
    for match in re.finditer(r"github\.com/MenschMachine/pdfdancer-www/issues/(\d+)", body):
        numbers.add(int(match.group(1)))
    return sorted(numbers)


def resolve_issue_metadata(pr_data: dict | None, url_path: str) -> tuple[dict | None, bool]:
    if not pr_data:
        log.info("Issue lookup for %s: no PR data available", url_path)
        return None, False
    best_metadata = None
    best_score = -1
    has_explicit_issue_scope = False
    issue_numbers = extract_issue_numbers_from_pr(pr_data)
    log.info("Issue lookup for %s: candidate issue numbers=%s", url_path, issue_numbers)
    for issue_number in issue_numbers:
        issue = gh_issue(issue_number)
        if not issue:
            log.info("Issue lookup for %s: failed to load issue #%s", url_path, issue_number)
            continue
        parsed = parse_issue_like_body(issue.get("body", ""))
        action = parsed.get("action")
        diagnosis = parsed.get("diagnosis")
        if not action and not diagnosis:
            log.info("Issue lookup for %s: issue %s missing action/diagnosis", url_path, issue["url"])
            continue
        if parsed.get("page"):
            has_explicit_issue_scope = True
        score = url_matches_issue_page(url_path, parsed.get("page"))
        log.info(
            "Issue lookup for %s: issue=%s page=%r action=%r diagnosis=%r score=%d",
            url_path,
            issue["url"],
            parsed.get("page"),
            action,
            diagnosis,
            score,
        )
        if score == 0:
            if parsed.get("page") is None:
                score = 1
                log.info("Issue lookup for %s: issue %s has no page, using fallback score=%d", url_path, issue["url"], score)
            else:
                log.info("Issue lookup for %s: issue %s rejected due to page mismatch", url_path, issue["url"])
                continue
        metadata = {
            "source": issue["url"],
            "action": action,
            "diagnosis": diagnosis,
            "change": normalize_change(parsed.get("change_type") or action, parsed.get("must_change"), url_path),
        }
        if score > best_score:
            best_score = score
            best_metadata = metadata

    if best_metadata is not None:
        log.info("Metadata source for %s: linked issue %s (match_score=%d)", url_path, best_metadata["source"], best_score)
    else:
        log.info("Issue lookup for %s: no usable issue metadata", url_path)
    return best_metadata, has_explicit_issue_scope


def resolve_pr_metadata(pr_data: dict | None, url_path: str) -> dict | None:
    if not pr_data:
        log.info("PR body lookup for %s: no PR data available", url_path)
        return None
    parsed = parse_issue_like_body(pr_data.get("body", ""))
    if parsed.get("page") and normalize_path(parsed["page"]) != normalize_path(url_path):
        log.info(
            "PR body lookup for %s: rejected due to page mismatch page=%r pr=%s",
            url_path,
            parsed.get("page"),
            pr_data["url"],
        )
        return None
    action = parsed.get("change_type") or parsed.get("action")
    if not action and not parsed.get("diagnosis"):
        log.info("PR body lookup for %s: missing action/diagnosis in %s", url_path, pr_data["url"])
        return None
    log.info("Metadata source for %s: PR body %s", url_path, pr_data["url"])
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
    log.info("Metadata source for %s: git reconstruction from %s", url_path, commit_sha)
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


def has_equivalent_pending_entry(entries: list[dict], candidate: dict) -> bool:
    for entry in entries:
        if entry.get("status") != "pending":
            continue
        if entry.get("url") != candidate.get("url"):
            continue
        if entry.get("date_implemented") != candidate.get("date_implemented"):
            continue
        if entry.get("suggestion_source") != candidate.get("suggestion_source"):
            continue
        if entry.get("change") != candidate.get("change"):
            continue
        return True
    return False


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
    parser.add_argument(
        "--consider-unmerged-prs",
        action="store_true",
        help="Consider unmerged PR candidates for commit->PR resolution (useful for testing).",
    )
    args = parser.parse_args()

    implemented_on = date.fromisoformat(args.date) if args.date else date.today()
    payload = load_payload(args.payload_json)
    changed_paths = payload.get("changed_paths", [])
    if not changed_paths:
        raise RuntimeError(
            "Changed URL payload is empty. "
            f"before={payload.get('before')!r} after={payload.get('after')!r} "
            f"lastmod_path={payload.get('lastmod_path')!r}"
    )
    ledger_path = Path(args.ledger_path)
    data_dir = Path(args.data_dir)
    entries = load_ledger(ledger_path)

    log.info(
        "Tracking implementations from payload: before=%s after=%s changed_count=%d",
        payload.get("before"),
        payload.get("after"),
        len(changed_paths),
    )
    for url_path in changed_paths:
        log.info("Tracking implementation URL: %s", url_path)

    pr_data = gh_pr_for_commit(payload["after"], consider_unmerged_prs=args.consider_unmerged_prs)
    if pr_data is None:
        log.info("Commit %s is not associated with a PR via GitHub API", payload["after"])
    else:
        log.info("Resolved PR for commit %s: %s", payload["after"], pr_data.get("url"))
    compare_files = gh_compare_files(payload["before"], payload["after"])

    appended = []
    skipped = []
    for url_path in changed_paths:
        metadata, has_explicit_issue_scope = resolve_issue_metadata(pr_data, url_path)
        if metadata is None and has_explicit_issue_scope:
            log.info(
                "Metadata lookup for %s: skipped (outside linked issue page scope)",
                url_path,
            )
            skipped.append({"url": url_path, "reason": "outside linked issue scope"})
            continue
        if metadata is None:
            log.info("Metadata lookup for %s: falling back to PR body", url_path)
            metadata = resolve_pr_metadata(pr_data, url_path)
        if metadata is None:
            log.info("Metadata lookup for %s: falling back to git reconstruction", url_path)
            metadata = resolve_git_metadata(compare_files, url_path, payload["after"])
        entry = build_entry(url_path, metadata, implemented_on, data_dir)
        if has_equivalent_pending_entry(entries, entry):
            log.info("Tracking for %s: skipped (equivalent pending entry already exists)", url_path)
            skipped.append({"url": url_path, "reason": "equivalent pending entry already exists"})
            continue
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
