"""Tests for scripts/propagate-prod-setup.py."""

import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the script as a module
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

_spec = spec_from_file_location("propagate_prod_setup", SCRIPTS_DIR / "propagate-prod-setup.py")
_mod = module_from_spec(_spec)
_spec.loader.exec_module(_mod)

setup_webhooks = _mod.setup_webhooks
teardown_webhooks = _mod.teardown_webhooks
clear_webhooks = _mod.clear_webhooks


@pytest.fixture
def state_file(tmp_path):
    return tmp_path / ".webhooks.json"


class TestSetupWebhooks:
    def test_dry_run_does_not_create_state(self, state_file):
        setup_webhooks(
            repos=["owner/repo"],
            state_file=state_file,
            url="https://webhook.example.com/webhook",
            events="push,pull_request",
            secret="s3cret",
            dry_run=True,
        )
        assert not state_file.exists()

    @patch("subprocess.run")
    def test_creates_webhook_and_writes_state(self, mock_run, state_file):
        mock_run.return_value = MagicMock(stdout="12345\n", returncode=0)

        setup_webhooks(
            repos=["owner/repo"],
            state_file=state_file,
            url="https://wh.example.com/webhook",
            events="push",
            secret="abc",
            dry_run=False,
        )

        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["url"] == "https://wh.example.com/webhook"
        assert state["secret"] == "abc"
        assert len(state["webhooks"]) == 1
        assert state["webhooks"][0]["repo"] == "owner/repo"
        assert state["webhooks"][0]["hook_id"] == 12345

        # Verify gh api was called correctly
        cmd = mock_run.call_args[0][0]
        assert "repos/owner/repo/hooks" in cmd
        assert "-f" in cmd
        idx = cmd.index("config[url]=https://wh.example.com/webhook")
        assert idx > 0

    @patch("subprocess.run")
    def test_skips_existing_repos(self, mock_run, state_file):
        # Pre-populate state
        state_file.write_text(json.dumps({
            "url": "https://wh.example.com/webhook",
            "secret": "abc",
            "webhooks": [{"repo": "owner/repo", "hook_id": 111}],
        }))

        setup_webhooks(
            repos=["owner/repo"],
            state_file=state_file,
            url="https://wh.example.com/webhook",
            events="push",
            secret="abc",
            dry_run=False,
        )

        # No gh api call should be made
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_appends_new_repos_to_existing_state(self, mock_run, state_file):
        state_file.write_text(json.dumps({
            "url": "https://wh.example.com/webhook",
            "secret": "abc",
            "webhooks": [{"repo": "owner/repo-a", "hook_id": 111}],
        }))

        mock_run.return_value = MagicMock(stdout="222\n", returncode=0)

        setup_webhooks(
            repos=["owner/repo-a", "owner/repo-b"],
            state_file=state_file,
            url="https://wh.example.com/webhook",
            events="push",
            secret="abc",
            dry_run=False,
        )

        state = json.loads(state_file.read_text())
        assert len(state["webhooks"]) == 2
        repos_in_state = {wh["repo"] for wh in state["webhooks"]}
        assert repos_in_state == {"owner/repo-a", "owner/repo-b"}


class TestTeardownWebhooks:
    def test_teardown_removes_state_file(self, state_file):
        state_file.write_text(json.dumps({
            "url": "https://wh.example.com/webhook",
            "secret": "abc",
            "webhooks": [{"repo": "owner/repo", "hook_id": 123}],
        }))

        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            teardown_webhooks(state_file, dry_run=False)

        assert not state_file.exists()

    def test_teardown_dry_run_keeps_state(self, state_file):
        state_file.write_text(json.dumps({
            "url": "https://wh.example.com/webhook",
            "secret": "abc",
            "webhooks": [{"repo": "owner/repo", "hook_id": 123}],
        }))

        with patch("subprocess.run") as mock_run:
            teardown_webhooks(state_file, dry_run=True)

        assert state_file.exists()
        mock_run.assert_not_called()

    def test_teardown_missing_state_exits(self, state_file):
        with pytest.raises(SystemExit):
            teardown_webhooks(state_file, dry_run=False)

    @patch("subprocess.run")
    def test_teardown_calls_delete_for_each_hook(self, mock_run, state_file):
        mock_run.return_value = MagicMock(returncode=0)
        state_file.write_text(json.dumps({
            "url": "https://wh.example.com/webhook",
            "secret": "abc",
            "webhooks": [
                {"repo": "owner/a", "hook_id": 1},
                {"repo": "owner/b", "hook_id": 2},
            ],
        }))

        teardown_webhooks(state_file, dry_run=False)

        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("repos/owner/a/hooks/1" in cmd for cmd in cmds)
        assert any("repos/owner/b/hooks/2" in cmd for cmd in cmds)


class TestClearWebhooks:
    @patch("subprocess.run")
    def test_clear_deletes_all_hooks(self, mock_run, state_file):
        # First call: list hooks, second+third: delete
        mock_run.side_effect = [
            MagicMock(stdout="100\n200\n", returncode=0),  # list
            MagicMock(returncode=0),  # delete 100
            MagicMock(returncode=0),  # delete 200
        ]

        clear_webhooks(["owner/repo"], state_file, dry_run=False)

        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("repos/owner/repo/hooks/100" in cmd for cmd in cmds)
        assert any("repos/owner/repo/hooks/200" in cmd for cmd in cmds)

    @patch("subprocess.run")
    def test_clear_dry_run(self, mock_run, state_file):
        mock_run.return_value = MagicMock(stdout="100\n", returncode=0)

        clear_webhooks(["owner/repo"], state_file, dry_run=True)

        # Only the list call should happen
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    def test_clear_removes_state_file(self, mock_run, state_file):
        state_file.write_text("{}")
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        clear_webhooks(["owner/repo"], state_file, dry_run=False)

        assert not state_file.exists()

    @patch("subprocess.run")
    def test_clear_no_hooks_found(self, mock_run, state_file):
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        clear_webhooks(["owner/repo"], state_file, dry_run=False)

        # Only the list call
        assert mock_run.call_count == 1
