import hashlib
import hmac
import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from propagate_app.signal_transport import bind_pull_socket, close_pull_socket, close_push_socket, connect_push_socket, receive_signal
from propagate_webhook.cli import build_parser
from propagate_webhook.server import create_app

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


@pytest.fixture
def zmq_socket():
    address = "ipc:///tmp/propagate-test-webhook.sock"
    pull = bind_pull_socket(address)
    yield pull, address
    close_pull_socket(pull, address)


@pytest.fixture
def app(zmq_socket):
    _, address = zmq_socket
    signals = {
        "pull_request.labeled": object(),
        "push": object(),
        "issue_comment.created": object(),
    }
    application = create_app(config_signals=signals, zmq_address=address, secret=None)
    application.state.push_socket = connect_push_socket(address)
    yield application
    if application.state.push_socket is not None:
        close_push_socket(application.state.push_socket)
        application.state.push_socket = None


@pytest.fixture
def app_with_secret(zmq_socket):
    _, address = zmq_socket
    signals = {"pull_request.labeled": object()}
    application = create_app(config_signals=signals, zmq_address=address, secret="test-secret")
    application.state.push_socket = connect_push_socket(address)
    yield application
    if application.state.push_socket is not None:
        close_push_socket(application.state.push_socket)
        application.state.push_socket = None


@pytest.mark.anyio
async def test_webhook_delivers_pr_labeled_signal(app, zmq_socket):
    pull, _ = zmq_socket
    body = {
        "action": "labeled",
        "label": {"name": "approved"},
        "pull_request": {
            "number": 42,
            "head": {"ref": "feature"},
            "base": {"ref": "main"},
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "alice"},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook", json=body, headers={"X-GitHub-Event": "pull_request"})
    assert response.status_code == 200
    assert response.json()["status"] == "delivered"
    assert response.json()["signal"] == "pull_request.labeled"

    result = receive_signal(pull, block=True, timeout_ms=2000)
    assert result is not None
    signal_type, payload = result
    assert signal_type == "pull_request.labeled"
    assert payload["pr_number"] == 42
    assert payload["label"] == "approved"


@pytest.mark.anyio
async def test_webhook_delivers_push_signal(app, zmq_socket):
    pull, _ = zmq_socket
    body = {
        "ref": "refs/heads/main",
        "head_commit": {"id": "abc123"},
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "bob"},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook", json=body, headers={"X-GitHub-Event": "push"})
    assert response.status_code == 200
    assert response.json()["status"] == "delivered"

    result = receive_signal(pull, block=True, timeout_ms=2000)
    assert result is not None
    assert result[0] == "push"
    assert result[1]["ref"] == "refs/heads/main"


@pytest.mark.anyio
async def test_webhook_ignores_unsupported_event(app):
    body = {"zen": "Keep it simple"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook", json=body, headers={"X-GitHub-Event": "ping"})
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "unsupported_event"


@pytest.mark.anyio
async def test_webhook_ignores_signal_not_in_config(app):
    body = {
        "action": "opened",
        "pull_request": {
            "number": 1,
            "head": {"ref": "x"},
            "base": {"ref": "main"},
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "alice"},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook", json=body, headers={"X-GitHub-Event": "pull_request"})
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "unknown_signal"


@pytest.mark.anyio
async def test_webhook_validates_hmac_signature(app_with_secret, zmq_socket):
    pull, _ = zmq_socket
    body = json.dumps({
        "action": "labeled",
        "label": {"name": "deploy"},
        "pull_request": {
            "number": 5,
            "head": {"ref": "x"},
            "base": {"ref": "main"},
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "alice"},
    }).encode()
    signature = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app_with_secret), base_url="http://test") as client:
        response = await client.post(
            "/webhook",
            content=body,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 200
    assert response.json()["status"] == "delivered"


@pytest.mark.anyio
async def test_webhook_rejects_invalid_signature(app_with_secret):
    body = json.dumps({"action": "labeled"}).encode()
    async with AsyncClient(transport=ASGITransport(app=app_with_secret), base_url="http://test") as client:
        response = await client.post(
            "/webhook",
            content=body,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": "sha256=invalid",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_webhook_rejects_missing_signature_when_secret_configured(app_with_secret):
    body = json.dumps({"action": "labeled"}).encode()
    async with AsyncClient(transport=ASGITransport(app=app_with_secret), base_url="http://test") as client:
        response = await client.post(
            "/webhook",
            content=body,
            headers={
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_webhook_returns_503_when_socket_not_connected(zmq_socket):
    """Without lifespan or manual setup, push_socket is None — should return 503."""
    _, address = zmq_socket
    signals = {"pull_request.labeled": object()}
    application = create_app(config_signals=signals, zmq_address=address, secret=None)
    assert application.state.push_socket is None

    body = {
        "action": "labeled",
        "label": {"name": "approved"},
        "pull_request": {"number": 1, "head": {"ref": "x"}, "base": {"ref": "main"}},
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "alice"},
    }
    async with AsyncClient(transport=ASGITransport(app=application, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post("/webhook", json=body, headers={"X-GitHub-Event": "pull_request"})
    assert response.status_code == 503


def test_debug_flag_sets_debug_level():
    parser = build_parser()
    args = parser.parse_args(["--config", "test.yaml", "--debug"])
    assert args.debug is True


def test_no_debug_flag_default():
    parser = build_parser()
    args = parser.parse_args(["--config", "test.yaml"])
    assert args.debug is False


@pytest.mark.anyio
async def test_webhook_logs_on_delivery(app, zmq_socket, caplog):
    body = {
        "action": "labeled",
        "label": {"name": "approved"},
        "pull_request": {
            "number": 42,
            "head": {"ref": "feature"},
            "base": {"ref": "main"},
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "alice"},
    }
    with caplog.at_level(logging.INFO, logger="propagate.webhook"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/webhook", json=body, headers={"X-GitHub-Event": "pull_request"})

    assert any("Webhook received: event=pull_request repo=owner/repo sender=alice" in r.message for r in caplog.records)
    assert any("Delivered signal 'pull_request.labeled' for owner/repo" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_webhook_logs_ignored_event(app, caplog):
    body = {"zen": "Keep it simple"}
    with caplog.at_level(logging.INFO, logger="propagate.webhook"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/webhook", json=body, headers={"X-GitHub-Event": "ping"})

    assert any("Unsupported event type 'ping'; ignoring." in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_webhook_logs_unknown_signal(app, caplog):
    body = {
        "action": "opened",
        "pull_request": {
            "number": 1,
            "head": {"ref": "x"},
            "base": {"ref": "main"},
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "alice"},
    }
    with caplog.at_level(logging.INFO, logger="propagate.webhook"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/webhook", json=body, headers={"X-GitHub-Event": "pull_request"})

    assert any("Signal 'pull_request.opened' not defined in config; ignoring." in r.message for r in caplog.records)
