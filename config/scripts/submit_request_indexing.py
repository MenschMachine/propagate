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
    filepath = "src/data/lastmod.json"

    # Ensure we have history to compare if we are in a shallow clone
    subprocess.run(["git", "fetch", "origin", "main"], capture_output=True)

    old_data = get_git_file_content("HEAD~1", filepath)
    new_data = get_git_file_content("HEAD", filepath)

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