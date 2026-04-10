#!/usr/bin/env python3
"""Determine changed URLs and request Google to re-crawl them via the Indexing API."""

import json
import logging
import os
import sys
from pathlib import Path

from changed_url_payload import build_changed_url_payload
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_ROOT = SCRIPT_DIR.parent
REPO_ROOT = CONFIG_ROOT.parent
SCOPES = ["https://www.googleapis.com/auth/indexing"]
load_dotenv(REPO_ROOT / ".env")

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
    parser.add_argument("--payload-json", help="Precomputed changed-url payload")
    args = parser.parse_args()

    if args.payload_json:
        payload = json.loads(args.payload_json)
    else:
        payload = build_changed_url_payload(args.before, args.after)

    changed_urls = payload["changed_urls"]

    if not changed_urls:
        log.debug("No pages changed in lastmod.json. No URLs to submit for indexing.")
        print("No pages changed in lastmod.json.")
        sys.exit(0)

    log.debug("Submitting %d URLs for indexing", len(changed_urls))
    print("Submitting URLs:\n" + "\n".join(changed_urls))

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
