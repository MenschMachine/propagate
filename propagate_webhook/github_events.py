from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("propagate.webhook")

SUPPORTED_EVENT_TYPES = {"pull_request", "push", "issues", "issue_comment", "pull_request_review_comment"}


def parse_github_event(event_type: str, body: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    if event_type not in SUPPORTED_EVENT_TYPES:
        logger.debug("Event type '%s' not in supported types; skipping.", event_type)
        return None
    action = body.get("action")
    signal_name = f"{event_type}.{action}" if action else event_type
    extractor = _EXTRACTORS.get(event_type)
    if extractor is None:
        logger.debug("No extractor for event type '%s'.", event_type)
        return None
    payload = extractor(body)
    logger.debug("Extracted signal '%s' from event '%s'.", signal_name, event_type)
    return signal_name, payload


def extract_pull_request_payload(body: dict[str, Any]) -> dict[str, Any]:
    pr = body.get("pull_request", {})
    repo = body.get("repository", {})
    payload: dict[str, Any] = {
        "repository": repo.get("full_name", ""),
        "pr_number": pr.get("number", 0),
        "merged": bool(pr.get("merged", False)),
        "action": body.get("action", ""),
        "head_ref": pr.get("head", {}).get("ref", ""),
        "base_ref": pr.get("base", {}).get("ref", ""),
        "sender": body.get("sender", {}).get("login", ""),
    }
    if body.get("action") in ("labeled", "unlabeled"):
        label = body.get("label", {})
        payload["label"] = label.get("name", "")
    return payload


def extract_push_payload(body: dict[str, Any]) -> dict[str, Any]:
    repo = body.get("repository", {})
    head_commit = body.get("head_commit") or {}
    return {
        "repository": repo.get("full_name", ""),
        "ref": body.get("ref", ""),
        "head_commit_sha": head_commit.get("id", ""),
        "sender": body.get("sender", {}).get("login", ""),
    }


def extract_issue_comment_payload(body: dict[str, Any]) -> dict[str, Any]:
    issue = body.get("issue", {})
    comment = body.get("comment", {})
    repo = body.get("repository", {})
    return {
        "repository": repo.get("full_name", ""),
        "issue_number": issue.get("number", 0),
        "comment_body": comment.get("body", ""),
        "is_pull_request": "pull_request" in issue,
        "sender": body.get("sender", {}).get("login", ""),
    }


def extract_issues_payload(body: dict[str, Any]) -> dict[str, Any]:
    issue = body.get("issue", {})
    repo = body.get("repository", {})
    payload: dict[str, Any] = {
        "repository": repo.get("full_name", ""),
        "issue_number": issue.get("number", 0),
        "issue_title": issue.get("title", ""),
        "issue_body": issue.get("body", ""),
        "state": issue.get("state", ""),
        "action": body.get("action", ""),
        "sender": body.get("sender", {}).get("login", ""),
    }
    if body.get("action") in ("labeled", "unlabeled"):
        label = body.get("label", {})
        payload["label"] = label.get("name", "")
    return payload


def extract_pull_request_review_comment_payload(body: dict[str, Any]) -> dict[str, Any]:
    comment = body.get("comment", {})
    pr = body.get("pull_request", {})
    repo = body.get("repository", {})
    return {
        "repository": repo.get("full_name", ""),
        "pr_number": pr.get("number", 0),
        "path": comment.get("path", ""),
        "line": comment.get("line", 0),
        "body": comment.get("body", ""),
        "author": comment.get("user", {}).get("login", ""),
        "action": body.get("action", ""),
        "sender": body.get("sender", {}).get("login", ""),
    }


_EXTRACTORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "pull_request": extract_pull_request_payload,
    "push": extract_push_payload,
    "issues": extract_issues_payload,
    "issue_comment": extract_issue_comment_payload,
    "pull_request_review_comment": extract_pull_request_review_comment_payload,
}
