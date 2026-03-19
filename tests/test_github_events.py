from propagate_webhook.github_events import parse_github_event


def test_pull_request_labeled():
    body = {
        "action": "labeled",
        "label": {"name": "approved"},
        "pull_request": {
            "number": 42,
            "head": {"ref": "feature-branch"},
            "base": {"ref": "main"},
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "alice"},
    }
    result = parse_github_event("pull_request", body)
    assert result is not None
    signal_name, payload = result
    assert signal_name == "pull_request.labeled"
    assert payload["repository"] == "owner/repo"
    assert payload["pr_number"] == 42
    assert payload["label"] == "approved"
    assert payload["head_ref"] == "feature-branch"
    assert payload["base_ref"] == "main"
    assert payload["sender"] == "alice"
    assert payload["action"] == "labeled"


def test_pull_request_opened_has_no_label_field():
    body = {
        "action": "opened",
        "pull_request": {
            "number": 10,
            "head": {"ref": "my-branch"},
            "base": {"ref": "main"},
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "bob"},
    }
    result = parse_github_event("pull_request", body)
    assert result is not None
    signal_name, payload = result
    assert signal_name == "pull_request.opened"
    assert "label" not in payload


def test_push_event():
    body = {
        "ref": "refs/heads/main",
        "head_commit": {"id": "abc123def"},
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "carol"},
    }
    result = parse_github_event("push", body)
    assert result is not None
    signal_name, payload = result
    assert signal_name == "push"
    assert payload["ref"] == "refs/heads/main"
    assert payload["head_commit_sha"] == "abc123def"
    assert payload["repository"] == "owner/repo"
    assert payload["sender"] == "carol"


def test_push_event_without_head_commit():
    body = {
        "ref": "refs/heads/main",
        "head_commit": None,
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "carol"},
    }
    result = parse_github_event("push", body)
    assert result is not None
    _, payload = result
    assert payload["head_commit_sha"] == ""


def test_issue_comment_created():
    body = {
        "action": "created",
        "issue": {
            "number": 99,
            "pull_request": {"url": "https://api.github.com/..."},
        },
        "comment": {"body": "LGTM"},
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "dave"},
    }
    result = parse_github_event("issue_comment", body)
    assert result is not None
    signal_name, payload = result
    assert signal_name == "issue_comment.created"
    assert payload["issue_number"] == 99
    assert payload["comment_body"] == "LGTM"
    assert payload["is_pull_request"] is True
    assert payload["sender"] == "dave"


def test_issue_comment_on_issue_not_pr():
    body = {
        "action": "created",
        "issue": {"number": 5},
        "comment": {"body": "hello"},
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "eve"},
    }
    result = parse_github_event("issue_comment", body)
    assert result is not None
    _, payload = result
    assert payload["is_pull_request"] is False


def test_issues_labeled():
    body = {
        "action": "labeled",
        "label": {"name": "approved"},
        "issue": {
            "number": 17,
            "title": "Implement docs refresh",
            "body": "Please update the website.",
            "state": "open",
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "frank"},
    }
    result = parse_github_event("issues", body)
    assert result is not None
    signal_name, payload = result
    assert signal_name == "issues.labeled"
    assert payload["repository"] == "owner/repo"
    assert payload["issue_number"] == 17
    assert payload["label"] == "approved"
    assert payload["issue_title"] == "Implement docs refresh"
    assert payload["issue_body"] == "Please update the website."
    assert payload["state"] == "open"
    assert payload["sender"] == "frank"
    assert payload["action"] == "labeled"


def test_issues_opened_has_no_label_field():
    body = {
        "action": "opened",
        "issue": {
            "number": 3,
            "title": "New feature",
            "body": "",
            "state": "open",
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "grace"},
    }
    result = parse_github_event("issues", body)
    assert result is not None
    signal_name, payload = result
    assert signal_name == "issues.opened"
    assert "label" not in payload


def test_issues_reopened_has_no_label_field():
    body = {
        "action": "reopened",
        "issue": {
            "number": 4,
            "title": "Retry feature",
            "body": "Reopen this workflow item.",
            "state": "open",
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "heidi"},
    }
    result = parse_github_event("issues", body)
    assert result is not None
    signal_name, payload = result
    assert signal_name == "issues.reopened"
    assert payload["issue_number"] == 4
    assert "label" not in payload


def test_issues_unlabeled():
    body = {
        "action": "unlabeled",
        "label": {"name": "approved"},
        "issue": {
            "number": 18,
            "title": "Remove approval",
            "body": "Undo this label.",
            "state": "open",
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "ivan"},
    }
    result = parse_github_event("issues", body)
    assert result is not None
    signal_name, payload = result
    assert signal_name == "issues.unlabeled"
    assert payload["issue_number"] == 18
    assert payload["label"] == "approved"


def test_unsupported_event_returns_none():
    result = parse_github_event("deployment", {"action": "created"})
    assert result is None


def test_ping_event_returns_none():
    result = parse_github_event("ping", {"zen": "Keep it simple"})
    assert result is None
