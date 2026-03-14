#!/usr/bin/env python3
"""Parse propagate config and output GitHub owner/repo pairs."""

import argparse
import logging
import re
import subprocess
from pathlib import Path

import yaml

from propagate_app.constants import configure_logging

logger = logging.getLogger("propagate.smee-parse-repos")


def parse_github_url(url: str) -> str | None:
    """Extract owner/repo from a GitHub URL (https or git@ format)."""
    m = re.match(r"https?://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if m:
        return m.group(1)
    m = re.match(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1)
    return None


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Extract GitHub repos from propagate config")
    parser.add_argument("--config", required=True, help="Path to propagate YAML config")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config_dir = config_path.parent

    with open(config_path) as f:
        config = yaml.safe_load(f)

    repos = config.get("repositories", {})
    for name, repo_data in repos.items():
        url = repo_data.get("url")
        if url:
            owner_repo = parse_github_url(url)
            if owner_repo:
                print(owner_repo)
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
                print(owner_repo)
            else:
                logger.warning("'%s' origin is not a GitHub URL: %s", name, origin_url)
        except subprocess.CalledProcessError:
            logger.warning("'%s' could not get origin URL from %s", name, repo_path)


if __name__ == "__main__":
    main()
