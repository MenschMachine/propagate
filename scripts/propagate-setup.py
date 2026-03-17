#!/usr/bin/env python3
"""Set up smee webhooks and GitHub labels for a propagate config."""

import argparse
import json
import logging
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import yaml

logger = logging.getLogger("propagate.setup")


def parse_github_url(url: str) -> str | None:
    """Extract owner/repo from a GitHub URL (https or git@ format)."""
    m = re.match(r"https?://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if m:
        return m.group(1)
    m = re.match(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1)
    return None


def extract_repos(config: dict, config_dir: Path) -> list[str]:
    """Extract unique owner/repo strings from config repositories."""
    repos = []
    for name, repo_data in config.get("repositories", {}).items():
        url = repo_data.get("url")
        if url:
            owner_repo = parse_github_url(url)
            if owner_repo:
                repos.append(owner_repo)
            else:
                logger.warning("'%s' URL is not a GitHub URL: %s", name, url)
            continue

        path_value = repo_data.get("path")
        if not path_value:
            logger.warning("'%s' has no url or path", name)
            continue

        repo_path = Path(path_value).expanduser()
        if not repo_path.is_absolute():
            repo_path = config_dir / repo_path
        repo_path = repo_path.resolve()

        try:
            result = subprocess.run(
                ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
                capture_output=True, text=True, check=True,
            )
            origin_url = result.stdout.strip()
            owner_repo = parse_github_url(origin_url)
            if owner_repo:
                repos.append(owner_repo)
            else:
                logger.warning("'%s' origin is not a GitHub URL: %s", name, origin_url)
        except subprocess.CalledProcessError:
            logger.warning("'%s' could not get origin URL from %s", name, repo_path)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for r in repos:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def extract_labels(config: dict) -> list[str]:
    """Extract all labels used in the config from routes, propagation triggers, and hooks."""
    labels = set()

    # 1. executions[*].sub_tasks[*].routes[*].when.label
    for exec_data in config.get("executions", {}).values():
        for task in exec_data.get("sub_tasks", []):
            for route in task.get("routes", []):
                label = route.get("when", {}).get("label")
                if label:
                    labels.add(label)

    # 2. propagation.triggers[*].when.label
    for trigger in config.get("propagation", {}).get("triggers", []):
        label = trigger.get("when", {}).get("label")
        if label:
            labels.add(label)

    # 3. git:pr-labels-add <args> in before/after/on_failure hooks
    label_cmd_re = re.compile(r"^git:pr-labels-add\s+(.+)$")
    for exec_data in config.get("executions", {}).values():
        for task in exec_data.get("sub_tasks", []):
            for hook_key in ("before", "after", "on_failure"):
                for cmd in task.get(hook_key, []):
                    if not isinstance(cmd, str):
                        continue
                    m = label_cmd_re.match(cmd)
                    if not m:
                        continue
                    for arg in m.group(1).split():
                        # Skip context key references
                        if not arg.startswith(":"):
                            labels.add(arg)

    return sorted(labels)


def setup_smee(repos: list[str], state_file: Path, port: int, events: str, secret: str, dry_run: bool) -> None:
    """Set up smee channel and webhooks for repos not already in state file."""
    existing_repos = set()
    state = None

    if state_file.exists():
        with open(state_file) as f:
            state = json.load(f)
        for wh in state.get("webhooks", []):
            existing_repos.add(wh["repo"])

    new_repos = [r for r in repos if r not in existing_repos]

    if not new_repos:
        logger.info("All repos already have webhooks in %s — nothing to do", state_file)
        return

    if existing_repos:
        logger.info("Repos already in %s: %s", state_file.name, ", ".join(sorted(existing_repos)))
    logger.info("New repos to set up: %s", ", ".join(new_repos))

    if dry_run:
        logger.info("[dry-run] Would create smee channel and webhooks for: %s", ", ".join(new_repos))
        return

    # Get or create channel URL
    if state:
        channel_url = state["channel_url"]
        logger.info("Reusing existing channel: %s", channel_url)
    else:
        logger.info("Creating new smee channel...")
        result = subprocess.run(
            ["curl", "-Ls", "-o", "/dev/null", "-w", "%{url_effective}", "https://smee.io/new"],
            capture_output=True, text=True, check=True,
        )
        channel_url = result.stdout.strip()
        logger.info("Channel: %s", channel_url)

    # Build event flags
    event_list = [e.strip() for e in events.split(",")]
    event_flags = []
    for evt in event_list:
        event_flags.extend(["-f", f"events[]={evt}"])

    # Create webhooks for new repos
    new_webhooks = []
    for repo in new_repos:
        logger.info("Creating webhook for %s...", repo)
        cmd = [
            "gh", "api", f"repos/{repo}/hooks", "--method", "POST",
            "-f", f"config[url]={channel_url}",
            "-f", "config[content_type]=json",
            "-f", f"config[secret]={secret}",
            "-F", "active=true",
            *event_flags,
            "-q", ".id",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        hook_id = int(result.stdout.strip())
        logger.info("  Hook ID: %d", hook_id)
        new_webhooks.append({"repo": repo, "hook_id": hook_id})

    # Update state file
    if state:
        state["webhooks"].extend(new_webhooks)
    else:
        state = {
            "channel_url": channel_url,
            "port": port,
            "secret": secret,
            "webhooks": new_webhooks,
        }

    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")

    logger.info("State written to %s", state_file)


def ensure_labels(repos: list[str], labels: list[str], dry_run: bool) -> None:
    """Create missing labels on each GitHub repo."""
    if not labels:
        logger.info("No labels to create")
        return

    for repo in repos:
        logger.info("Checking labels on %s...", repo)
        result = subprocess.run(
            ["gh", "label", "list", "--repo", repo, "--limit", "200", "--json", "name", "-q", ".[].name"],
            capture_output=True, text=True, check=True,
        )
        existing = set(result.stdout.strip().splitlines())

        missing = [l for l in labels if l not in existing]
        if not missing:
            logger.info("  All labels exist")
            continue

        for label in missing:
            if dry_run:
                logger.info("  [dry-run] Would create label: %s", label)
            else:
                logger.info("  Creating label: %s", label)
                subprocess.run(
                    ["gh", "label", "create", label, "--repo", repo, "--force"],
                    capture_output=True, text=True, check=True,
                )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Set up smee webhooks and GitHub labels for a propagate config")
    parser.add_argument("--config", required=True, help="Path to propagate YAML config")
    parser.add_argument("--port", type=int, default=8080, help="Smee proxy port (default: 8080)")
    parser.add_argument("--events", default="push,pull_request,issue_comment", help="Webhook events (comma-separated)")
    parser.add_argument("--secret", default=None, help="Webhook secret (auto-generated if omitted)")
    parser.add_argument("--skip-smee", action="store_true", help="Skip smee webhook setup")
    parser.add_argument("--skip-labels", action="store_true", help="Skip label creation")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    args = parser.parse_args()

    # Check prerequisites
    try:
        subprocess.run(["gh", "auth", "status"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("'gh' is not authenticated. Run 'gh auth login' first.")
        sys.exit(1)

    config_path = Path(args.config).resolve()
    config_dir = config_path.parent

    with open(config_path) as f:
        config = yaml.safe_load(f)

    repos = extract_repos(config, config_dir)
    if not repos:
        logger.error("No GitHub repos found in config.")
        sys.exit(1)

    logger.info("Repos: %s", ", ".join(repos))

    labels = extract_labels(config)
    logger.info("Labels: %s", ", ".join(labels) if labels else "(none)")

    secret = args.secret or secrets.token_hex(20)

    project_dir = Path(__file__).resolve().parent.parent
    state_file = project_dir / ".smee.json"

    if not args.skip_smee:
        setup_smee(repos, state_file, args.port, args.events, secret, args.dry_run)

    if not args.skip_labels:
        ensure_labels(repos, labels, args.dry_run)

    logger.info("Done.")


if __name__ == "__main__":
    main()
