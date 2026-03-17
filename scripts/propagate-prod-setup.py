#!/usr/bin/env python3
"""Set up production GitHub webhooks and labels for a propagate config."""

import argparse
import json
import logging
import secrets
import subprocess
import sys
from pathlib import Path

import yaml

# Reuse helpers from the dev setup script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib.util import module_from_spec, spec_from_file_location

_spec = spec_from_file_location("propagate_setup", Path(__file__).resolve().parent / "propagate-setup.py")
_mod = module_from_spec(_spec)
_spec.loader.exec_module(_mod)

parse_github_url = _mod.parse_github_url
extract_repos = _mod.extract_repos
extract_labels = _mod.extract_labels
ensure_labels = _mod.ensure_labels

logger = logging.getLogger("propagate.prod-setup")


def setup_webhooks(repos: list[str], state_file: Path, url: str, events: str, secret: str, dry_run: bool) -> None:
    """Create GitHub webhooks pointing to the production URL."""
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
        logger.info("[dry-run] Would create webhooks for: %s", ", ".join(new_repos))
        return

    # Build event flags
    event_list = [e.strip() for e in events.split(",")]
    event_flags = []
    for evt in event_list:
        event_flags.extend(["-f", f"events[]={evt}"])

    # Create webhooks
    new_webhooks = []
    for repo in new_repos:
        logger.info("Creating webhook for %s → %s", repo, url)
        cmd = [
            "gh", "api", f"repos/{repo}/hooks", "--method", "POST",
            "-f", f"config[url]={url}",
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
            "url": url,
            "secret": secret,
            "webhooks": new_webhooks,
        }

    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")

    logger.info("State written to %s", state_file)


def teardown_webhooks(state_file: Path, dry_run: bool) -> None:
    """Delete webhooks recorded in the state file."""
    if not state_file.exists():
        logger.error("%s not found. Nothing to tear down.", state_file)
        sys.exit(1)

    with open(state_file) as f:
        state = json.load(f)

    for wh in state.get("webhooks", []):
        repo = wh["repo"]
        hook_id = wh["hook_id"]
        if dry_run:
            logger.info("[dry-run] Would delete webhook %d from %s", hook_id, repo)
        else:
            logger.info("Deleting webhook %d from %s...", hook_id, repo)
            result = subprocess.run(
                ["gh", "api", f"repos/{repo}/hooks/{hook_id}", "--method", "DELETE"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                logger.info("  Deleted.")
            else:
                logger.info("  Already gone or failed (ignored).")

    if not dry_run:
        state_file.unlink()
        logger.info("Removed %s", state_file)


def clear_webhooks(repos: list[str], state_file: Path, dry_run: bool) -> None:
    """Remove ALL webhooks from each repo."""
    for repo in repos:
        logger.info("Listing webhooks on %s...", repo)
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/hooks", "-q", ".[].id"],
            capture_output=True, text=True, check=True,
        )
        hook_ids = [int(line) for line in result.stdout.strip().splitlines() if line.strip()]

        if not hook_ids:
            logger.info("  No webhooks found")
            continue

        for hook_id in hook_ids:
            if dry_run:
                logger.info("  [dry-run] Would delete webhook %d", hook_id)
            else:
                logger.info("  Deleting webhook %d...", hook_id)
                subprocess.run(
                    ["gh", "api", f"repos/{repo}/hooks/{hook_id}", "--method", "DELETE"],
                    capture_output=True, text=True,
                )

    if state_file.exists():
        if dry_run:
            logger.info("[dry-run] Would remove %s", state_file)
        else:
            state_file.unlink()
            logger.info("Removed %s", state_file)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Set up production GitHub webhooks and labels for a propagate config")
    parser.add_argument("--config", required=True, help="Path to propagate YAML config")
    parser.add_argument("--url", help="Production webhook URL (e.g. https://webhook.example.com/webhook)")
    parser.add_argument("--events", default="push,pull_request,issue_comment", help="Webhook events (comma-separated)")
    parser.add_argument("--secret", default=None, help="Webhook secret (auto-generated if omitted)")
    parser.add_argument("--skip-labels", action="store_true", help="Skip label creation")
    parser.add_argument("--teardown", action="store_true", help="Delete webhooks from state file")
    parser.add_argument("--clear", action="store_true", help="Remove ALL webhooks from repos in config")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    args = parser.parse_args()

    if args.teardown and args.clear:
        logger.error("--teardown and --clear are mutually exclusive")
        sys.exit(1)

    if not args.teardown and not args.clear and not args.url:
        logger.error("--url is required (unless using --teardown or --clear)")
        sys.exit(1)

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

    project_dir = Path(__file__).resolve().parent.parent
    state_file = project_dir / ".webhooks.json"

    if args.teardown:
        teardown_webhooks(state_file, args.dry_run)
        return

    if args.clear:
        clear_webhooks(repos, state_file, args.dry_run)
        return

    # Normal setup: webhooks + labels
    secret = args.secret or secrets.token_hex(20)

    setup_webhooks(repos, state_file, args.url, args.events, secret, args.dry_run)

    if not args.skip_labels:
        labels = extract_labels(config)
        logger.info("Labels: %s", ", ".join(labels) if labels else "(none)")
        ensure_labels(repos, labels, args.dry_run)

    logger.info("Done.")


if __name__ == "__main__":
    main()
