"""Evaluate SEO implementation ledger entries against GSC data.

Reads data/feedback/implementations.yaml, checks evaluation gates,
computes statistical significance, classifies outcomes, writes results
back to the ledger, and prints a JSON summary to stdout.

Run standalone: python evaluate_implementations.py
(from the marketing-data repo root)
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from datetime import date, datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

LEDGER_PATH = Path("data/feedback/implementations.yaml")
DATA_DIR = Path("data")

CALENDAR_FLOOR_DAYS = 14
CEILING_DAYS = 90

# Primary metric per suggestion type
METRIC_BY_TYPE = {
    "meta": "ctr",
    "content-edit": "ctr",
    "new-content": "impressions",
    "technical": "position",
}

# For these metrics, lower is better
LOWER_IS_BETTER = {"position"}


def load_page_content_for_url(data_dir: Path, url_path: str) -> dict | None:
    """Load the page content JSON for a URL from the latest data dir with a pages/ subdirectory."""
    data_dirs = list_data_dirs(data_dir)
    # Search from most recent to oldest
    for _, dir_path in reversed(data_dirs):
        pages_dir = dir_path / "pages"
        if not pages_dir.is_dir():
            continue
        filename = re.sub(r"[^a-zA-Z0-9]+", "_", url_path.strip("/")) + ".json"
        page_file = pages_dir / filename
        if page_file.exists():
            try:
                return json.loads(page_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
    return None


def check_deployment_status(entry: dict, page_content: dict | None) -> dict:
    """For meta entries with indexed_at_implementation, compare against current indexed content.

    Returns {"status": "confirmed_indexed" | "not_yet_indexed" | "unknown", "detail": "..."}.
    """
    if entry.get("suggestion_type") != "meta":
        return {"status": "unknown", "detail": "non-meta suggestion type"}

    snapshot = entry.get("indexed_at_implementation")
    if not snapshot:
        return {"status": "unknown", "detail": "no indexed_at_implementation snapshot"}

    if page_content is None:
        return {"status": "unknown", "detail": "no page content available"}

    old_title = snapshot.get("title", "")
    old_desc = snapshot.get("description", "")
    current_title = page_content.get("title", "")
    current_desc = page_content.get("meta_description", "")

    # Can't determine status without at least one non-empty field to compare
    if not old_title and not old_desc:
        return {"status": "unknown", "detail": "snapshot has no title or description to compare"}
    if not current_title and not current_desc:
        return {"status": "unknown", "detail": "page content has no title or description"}

    title_changed = bool(current_title) and current_title != old_title
    desc_changed = bool(current_desc) and current_desc != old_desc

    if title_changed or desc_changed:
        changed = []
        if title_changed:
            changed.append(f"title: {old_title!r} → {current_title!r}")
        if desc_changed:
            changed.append(f"description: {old_desc!r} → {current_desc!r}")
        return {
            "status": "confirmed_indexed",
            "detail": f"changed — {'; '.join(changed)}",
        }

    return {
        "status": "not_yet_indexed",
        "detail": "title and description still match pre-implementation values",
    }


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


def list_data_dirs(data_dir: Path) -> list[tuple[date, Path]]:
    """Return sorted (date, path) pairs for date-named directories under data/."""
    results = []
    if not data_dir.exists():
        return results
    for d in data_dir.iterdir():
        if d.is_dir():
            try:
                dt = datetime.strptime(d.name, "%Y-%m-%d").date()
                results.append((dt, d))
            except ValueError:
                continue
    results.sort(key=lambda x: x[0])
    return results


def load_gsc_data(gsc_path: Path) -> dict | None:
    if not gsc_path.exists():
        return None
    try:
        return json.loads(gsc_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def aggregate_by_page(gsc_data: dict) -> dict[str, dict]:
    """Aggregate query_page rows by page URL. Returns {page_path: {impressions, clicks, position, ctr}}."""
    page_totals: dict[str, dict] = {}
    for row in gsc_data.get("query_page", []):
        page_url = row.get("page", "")
        # Extract path from full URL
        path = extract_path(page_url)
        if not path:
            continue
        if path not in page_totals:
            page_totals[path] = {"impressions": 0, "clicks": 0, "weighted_position": 0.0}
        page_totals[path]["impressions"] += row.get("impressions", 0)
        page_totals[path]["clicks"] += row.get("clicks", 0)
        page_totals[path]["weighted_position"] += row.get("position", 0) * row.get("impressions", 0)

    for path, totals in page_totals.items():
        imp = totals["impressions"]
        totals["position"] = totals["weighted_position"] / imp if imp > 0 else 0.0
        totals["ctr"] = (totals["clicks"] / imp * 100) if imp > 0 else 0.0
        del totals["weighted_position"]

    return page_totals


def extract_path(url: str) -> str:
    """Extract path from a full URL or return as-is if already a path."""
    if url.startswith("/"):
        return url
    if "://" in url:
        # Extract path after domain
        after_scheme = url.split("://", 1)[1]
        slash_idx = after_scheme.find("/")
        if slash_idx == -1:
            return "/"
        return after_scheme[slash_idx:]
    return url


def get_post_change_weekly_data(
    entry: dict, data_dirs: list[tuple[date, Path]]
) -> list[dict]:
    """Collect weekly GSC metrics for a page after its implementation date."""
    impl_date = parse_date(entry["date_implemented"])
    page_path = entry["url"]

    post_dirs = [(d, p) for d, p in data_dirs if d > impl_date]
    if not post_dirs:
        return []

    # Each data dir represents a week of data. Aggregate per-dir.
    weeks = []
    for dir_date, dir_path in post_dirs:
        gsc_path = dir_path / "gsc.json"
        gsc_data = load_gsc_data(gsc_path)
        if gsc_data is None:
            continue
        page_data = aggregate_by_page(gsc_data)
        if page_path not in page_data:
            continue
        metrics = page_data[page_path]
        # Determine period from the gsc.json metadata
        start = gsc_data.get("start_date", dir_date.isoformat())
        end = gsc_data.get("end_date", dir_date.isoformat())
        weeks.append({
            "period": f"{start} to {end}",
            "impressions": metrics["impressions"],
            "clicks": metrics["clicks"],
            "ctr": round(metrics["ctr"], 2),
            "position": round(metrics["position"], 2),
        })

    return weeks


def parse_date(d: str | date) -> date:
    if isinstance(d, date):
        return d
    return datetime.strptime(str(d), "%Y-%m-%d").date()


def check_gates(entry: dict, today: date, post_impressions: int) -> str:
    """Check evaluation gates. Returns 'ready', 'ceiling', or 'pending'."""
    impl_date = parse_date(entry["date_implemented"])
    days_since = (today - impl_date).days

    # 90-day ceiling
    if days_since > CEILING_DAYS:
        return "ceiling"

    # Calendar floor
    if days_since < CALENDAR_FLOOR_DAYS:
        return "pending"

    # Volume gate
    if "min_impressions_for_eval" not in entry:
        log.debug("Entry %s missing min_impressions_for_eval, skipping", entry.get("url"))
        return "pending"
    if post_impressions >= entry["min_impressions_for_eval"]:
        return "ready"

    return "pending"


def compute_baseline_std(entry: dict, metric: str) -> float:
    """Compute standard deviation of a metric across baseline weeks."""
    weeks = entry.get("baseline", {}).get("weeks", [])
    values = [w[metric] for w in weeks if metric in w]
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def classify_outcome(
    entry: dict, post_weeks: list[dict]
) -> tuple[str, str]:
    """Classify as improved/declined/inconclusive/no_change. Returns (state, reason)."""
    suggestion_type = entry.get("suggestion_type", "meta")
    metric = METRIC_BY_TYPE.get(suggestion_type, "ctr")

    baseline_avg = entry.get("baseline", {}).get("averages", {}).get(metric)
    if baseline_avg is None:
        return "inconclusive", f"no baseline average for {metric}"

    std_dev = compute_baseline_std(entry, metric)

    post_values = [w[metric] for w in post_weeks if metric in w]
    if not post_values:
        return "inconclusive", f"no post-change data for {metric}"

    post_avg = sum(post_values) / len(post_values)
    delta = post_avg - baseline_avg
    threshold = 2 * std_dev

    lower_better = metric in LOWER_IS_BETTER

    if std_dev == 0:
        # No variance in baseline — any change is notable
        if abs(delta) < 0.01:
            return "no_change", f"{metric} unchanged at {baseline_avg}"
        if (delta < 0) == lower_better:
            return "improved", (
                f"{metric} changed from {baseline_avg} to {round(post_avg, 2)} "
                f"(baseline had zero variance)"
            )
        return "declined", (
            f"{metric} changed from {baseline_avg} to {round(post_avg, 2)} "
            f"(baseline had zero variance)"
        )

    direction_label = "decreased" if delta < 0 else "increased"
    abs_delta = abs(delta)

    if abs_delta <= 0.01 * max(abs(baseline_avg), 1):
        return "no_change", (
            f"{metric} effectively unchanged: {baseline_avg} → {round(post_avg, 2)}, "
            f"std dev {round(std_dev, 2)}"
        )

    is_better = (delta < 0) if lower_better else (delta > 0)

    if abs_delta > threshold:
        state = "improved" if is_better else "declined"
        return state, (
            f"{metric} {direction_label} from {baseline_avg} avg to {round(post_avg, 2)} "
            f"over {len(post_weeks)} weeks post-change, >2x baseline std dev ({round(std_dev, 2)})"
        )

    return "inconclusive", (
        f"{metric} {direction_label} from {baseline_avg} to {round(post_avg, 2)}, "
        f"within 2x baseline std dev ({round(std_dev, 2)})"
    )


def sum_impressions_from_weeks(post_weeks: list[dict]) -> int:
    """Sum impressions from already-loaded weekly data."""
    return sum(w.get("impressions", 0) for w in post_weeks)


def evaluate_entry(
    entry: dict, today: date, data_dirs: list[tuple[date, Path]]
) -> dict:
    """Evaluate a single pending entry. Returns the updated entry."""
    post_weeks = get_post_change_weekly_data(entry, data_dirs)
    post_impressions = sum_impressions_from_weeks(post_weeks)
    gate_result = check_gates(entry, today, post_impressions)

    if gate_result == "pending":
        return entry

    if gate_result == "ceiling":
        entry = dict(entry)
        entry["status"] = "evaluated"
        entry["evaluation"] = {
            "date": today.isoformat(),
            "state": "inconclusive",
            "reason": "insufficient_volume — hit 90-day ceiling without meeting evaluation gates",
            "post_change": {
                "weeks": post_weeks,
                "impressions_accumulated": post_impressions,
            },
        }
        return entry

    # gate_result == "ready"
    state, reason = classify_outcome(entry, post_weeks)
    entry = dict(entry)
    entry["status"] = "evaluated"
    entry["evaluation"] = {
        "date": today.isoformat(),
        "state": state,
        "reason": reason,
        "post_change": {
            "weeks": post_weeks,
            "impressions_accumulated": post_impressions,
        },
    }
    return entry


def collect_post_impressions(entries: list[dict], data_dirs: list[tuple[date, Path]]) -> dict[int, int]:
    """Collect post-implementation impressions for all pending entries in one pass over GSC data.

    Returns {entry_index: total_impressions} keyed by position in the entries list.
    """
    # Map entry index -> (url, impl_date)
    pending: dict[int, tuple[str, date]] = {}
    for i, e in enumerate(entries):
        if e.get("status") == "pending":
            pending[i] = (e["url"], parse_date(e["date_implemented"]))
    if not pending:
        return {}
    # Collect the set of URLs we care about
    urls_needed = {url for url, _ in pending.values()}
    # Single pass over data dirs
    totals: dict[int, int] = {i: 0 for i in pending}
    for dir_date, dir_path in data_dirs:
        gsc_path = dir_path / "gsc.json"
        gsc_data = load_gsc_data(gsc_path)
        if gsc_data is None:
            continue
        page_data = aggregate_by_page(gsc_data)
        relevant_pages = urls_needed & page_data.keys()
        if not relevant_pages:
            continue
        for i, (url, impl_date) in pending.items():
            if dir_date > impl_date and url in relevant_pages:
                totals[i] += page_data[url]["impressions"]
    return totals


def build_summary(entries: list[dict], newly_evaluated: list[dict], today: date, data_dirs: list[tuple[date, Path]], deployment_status: list[dict] | None = None) -> dict:
    """Build a JSON-serializable summary for downstream steps."""
    evaluated = []
    for e in newly_evaluated:
        evaluated.append({
            "url": e["url"],
            "suggestion_type": e.get("suggestion_type"),
            "state": e["evaluation"]["state"],
            "reason": e["evaluation"]["reason"],
        })

    pending_impressions = collect_post_impressions(entries, data_dirs)
    pending = []
    for i, e in enumerate(entries):
        if e.get("status") != "pending":
            continue
        impl_date = parse_date(e["date_implemented"])
        days = (today - impl_date).days
        min_imp = e.get("min_impressions_for_eval")
        if min_imp is None:
            continue
        post_imp = pending_impressions.get(i, 0)
        pending.append({
            "url": e["url"],
            "days_elapsed": days,
            "days_required": CALENDAR_FLOOR_DAYS,
            "impressions_accumulated": post_imp,
            "impressions_required": min_imp,
        })

    # Pattern summary across all evaluated entries (not just newly evaluated)
    all_evaluated = [e for e in entries if e.get("status") == "evaluated"]
    type_outcomes: dict[str, dict[str, int]] = {}
    insufficient_volume: list[str] = []
    for e in all_evaluated:
        st = e.get("suggestion_type", "unknown")
        state = e.get("evaluation", {}).get("state", "unknown")
        if st not in type_outcomes:
            type_outcomes[st] = {}
        type_outcomes[st][state] = type_outcomes[st].get(state, 0) + 1
        reason = e.get("evaluation", {}).get("reason", "")
        if "insufficient_volume" in reason:
            insufficient_volume.append(e["url"])

    result = {
        "newly_evaluated": evaluated,
        "pending": pending,
        "pattern_summary": type_outcomes,
        "insufficient_volume_urls": insufficient_volume,
    }
    if deployment_status is not None:
        result["deployment_status"] = deployment_status
    return result


def main(today: date | None = None, ledger_path: Path | None = None, data_dir: Path | None = None) -> str:
    if today is None:
        today = date.today()
    if ledger_path is None:
        ledger_path = LEDGER_PATH
    if data_dir is None:
        data_dir = DATA_DIR

    entries = load_ledger(ledger_path)
    if not entries:
        result = json.dumps({"newly_evaluated": [], "pending": [], "pattern_summary": {}, "insufficient_volume_urls": []})
        print(result)
        return result

    data_dirs = list_data_dirs(data_dir)
    newly_evaluated = []

    for i, entry in enumerate(entries):
        if entry.get("status") != "pending":
            continue
        updated = evaluate_entry(entry, today, data_dirs)
        if updated.get("status") == "evaluated":
            newly_evaluated.append(updated)
        entries[i] = updated

    if newly_evaluated:
        save_ledger(ledger_path, entries)

    # Deployment status check for pending entries with indexed_at_implementation snapshots
    deployment_status = []
    for entry in entries:
        if entry.get("status") != "pending":
            continue
        if not entry.get("indexed_at_implementation"):
            continue
        page_content = load_page_content_for_url(data_dir, entry["url"])
        status = check_deployment_status(entry, page_content)
        deployment_status.append({"url": entry["url"], **status})

    summary = build_summary(entries, newly_evaluated, today, data_dirs, deployment_status or None)
    result = json.dumps(summary)
    print(result)
    return result


if __name__ == "__main__":
    main()
