#!/usr/bin/env python3
"""Determine changed URLs and request Google to re-crawl them via the Indexing API."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCOPES = ["https://www.googleapis.com/auth/indexing"]
load_dotenv(REPO_ROOT / ".env")


def get_git_file_content(ref, filepath):
    try:
        result = subprocess.run(
            ['git', 'show', f"{ref}:{filepath}"],
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError:
        # File might not exist in the older ref
        return {}
    except json.JSONDecodeError:
        return {}


def get_credentials():
    creds_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_file:
        log.error("GOOGLE_APPLICATION_CREDENTIALS not set")
        sys.exit(1)
    return service_account.Credentials.from_service_account_file(
        creds_file, scopes=SCOPES
    )


def submit_url(service, url):
    #print("Submitting URL: %s", url)
    #return
    """Submit a URL_UPDATED notification."""
    body = {"url": url, "type": "URL_UPDATED"}
    return service.urlNotifications().publish(body=body).execute()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Submit changed URLs for indexing")
    parser.add_argument("--before", help="Git ref for previous state")
    parser.add_argument("--after", help="Git ref for current state")
    args = parser.parse_args()

    before_ref = args.before
    after_ref = args.after

    # Fallback to Propagate context store if not provided via CLI
    if not before_ref or not after_ref:
        context_root = os.environ.get("PROPAGATE_CONTEXT_ROOT")
        execution = os.environ.get("PROPAGATE_EXECUTION")
        if context_root and execution:
            context_dir = Path(context_root) / execution
            if not before_ref:
                before_file = context_dir / ":signal.before"
                if before_file.exists():
                    before_ref = before_file.read_text(encoding="utf-8").strip()
            if not after_ref:
                after_file = context_dir / ":signal.after"
                if after_file.exists():
                    after_ref = after_file.read_text(encoding="utf-8").strip()

    # Ultimate fallback if context store does not have it (e.g., manual execution without signals)
    if not before_ref:
        before_ref = "HEAD~1"
    if not after_ref:
        after_ref = "HEAD"

    log.debug("Comparing %s with %s", before_ref, after_ref)

    filepath = "src/data/lastmod.json"

    # Ensure we have history to compare if we are in a shallow clone
    subprocess.run(["git", "fetch", "origin", "main"], capture_output=True)

    old_data = get_git_file_content(before_ref, filepath)
    new_data = get_git_file_content(after_ref, filepath)

    changed_urls = []
    for path, mod_time in new_data.items():
        if old_data.get(path) != mod_time:
            # path is like "/" or "/terms-of-service/"
            # Ensure path starts with "/"
            if not path.startswith("/"):
                path = "/" + path
            url = f"https://pdfdancer.com{path}"
            changed_urls.append(url)

    if not changed_urls:
        log.debug("No pages changed in lastmod.json. No URLs to submit for indexing.")
        print("No pages changed in lastmod.json.")
        sys.exit(0)

    log.debug("Submitting %d URLs for indexing", len(changed_urls))
    print(f"Submitting URLs:\n" + "\n".join(changed_urls))

    credentials = get_credentials()
    service = build("indexing", "v3", credentials=credentials)

    results = []
    for url in changed_urls:
        try:
            response = submit_url(service, url)
            results.append({"url": url, "status": "submitted", "response": str(response)})
            log.debug("Submitted: %s", url)
        except Exception as e:
            results.append({"url": url, "status": "error", "error": str(e)})
            log.error("Failed to submit %s: %s", url, e)

    submitted = sum(1 for r in results if r["status"] == "submitted")
    failed = sum(1 for r in results if r["status"] == "error")
    log.debug("Indexing requests: %d submitted, %d failed", submitted, failed)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
    main()