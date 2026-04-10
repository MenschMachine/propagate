#!/usr/bin/env python3
"""Print changed production URLs and git refs as a JSON payload."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from changed_url_payload import build_changed_url_payload


def main() -> str:
    parser = argparse.ArgumentParser(description="Detect changed production URLs from lastmod.json")
    parser.add_argument("--before", help="Git ref for previous state")
    parser.add_argument("--after", help="Git ref for current state")
    args = parser.parse_args()

    payload = build_changed_url_payload(args.before, args.after)
    result = json.dumps(payload)
    print(result)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
    main()
