#!/usr/bin/env python3
"""Shared helpers for deriving changed production URLs from lastmod.json diffs."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

LASTMOD_PATH = "src/data/lastmod.json"
PRODUCTION_ORIGIN = "https://www.pdfdancer.com"


def get_git_file_content(ref: str, filepath: str, runner=subprocess.run) -> dict:
    try:
        result = runner(
            ["git", "show", f"{ref}:{filepath}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError:
        return {}
    except json.JSONDecodeError:
        return {}


def validate_git_ref(ref: str, runner=subprocess.run) -> None:
    try:
        runner(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"Invalid git ref: {ref!r}") from error


def read_signal_ref(context_dir: Path, name: str) -> str | None:
    ref_file = context_dir / f":signal.{name}"
    if not ref_file.exists():
        return None
    value = ref_file.read_text(encoding="utf-8").strip()
    return value or None


def normalize_git_ref(ref: str | None) -> str | None:
    if ref is None:
        return None
    trimmed = ref.strip()
    return trimmed or None


def resolve_git_refs(
    before_ref: str | None = None,
    after_ref: str | None = None,
    *,
    context_root: str | None = None,
    execution: str | None = None,
) -> tuple[str, str]:
    resolved_before = normalize_git_ref(before_ref)
    resolved_after = normalize_git_ref(after_ref)

    if (not resolved_before or not resolved_after) and context_root and execution:
        context_dir = Path(context_root) / execution
        if not resolved_before:
            resolved_before = normalize_git_ref(read_signal_ref(context_dir, "before"))
        if not resolved_after:
            resolved_after = normalize_git_ref(read_signal_ref(context_dir, "after"))

    if not resolved_before:
        resolved_before = "HEAD~1"
    if not resolved_after:
        resolved_after = "HEAD"
    return resolved_before, resolved_after


def build_changed_url_payload(
    before_ref: str | None = None,
    after_ref: str | None = None,
    *,
    lastmod_path: str = LASTMOD_PATH,
    origin: str = PRODUCTION_ORIGIN,
    runner=subprocess.run,
    context_root: str | None = None,
    execution: str | None = None,
) -> dict:
    before_ref, after_ref = resolve_git_refs(
        before_ref,
        after_ref,
        context_root=context_root or os.environ.get("PROPAGATE_CONTEXT_ROOT"),
        execution=execution or os.environ.get("PROPAGATE_EXECUTION"),
    )

    log.debug("Comparing %s with %s for %s", before_ref, after_ref, lastmod_path)

    validate_git_ref(before_ref, runner=runner)
    validate_git_ref(after_ref, runner=runner)
    runner(["git", "fetch", "origin", "main"], capture_output=True, text=True, check=False)

    old_data = get_git_file_content(before_ref, lastmod_path, runner=runner)
    new_data = get_git_file_content(after_ref, lastmod_path, runner=runner)

    if not new_data:
        raise RuntimeError(
            f"Unable to read {lastmod_path} at {after_ref}. "
            f"Computed refs were before={before_ref!r}, after={after_ref!r}."
        )

    changed_paths: list[str] = []
    for path, mod_time in new_data.items():
        normalized = path if path.startswith("/") else f"/{path}"
        if old_data.get(path) != mod_time:
            changed_paths.append(normalized)

    changed_paths = sorted(set(changed_paths))
    changed_urls = [f"{origin}{path}" for path in changed_paths]

    log.info("Changed URL payload: before=%s after=%s count=%d", before_ref, after_ref, len(changed_urls))
    for url in changed_urls:
        log.info("Changed URL payload item: %s", url)

    return {
        "before": before_ref,
        "after": after_ref,
        "lastmod_path": lastmod_path,
        "changed_count": len(changed_paths),
        "changed_paths": changed_paths,
        "changed_urls": changed_urls,
    }
