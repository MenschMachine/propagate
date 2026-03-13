from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "propagate.py"
CLI_PYTHON = REPO_ROOT / "venv" / "bin" / "python"
if not CLI_PYTHON.exists():
    CLI_PYTHON = Path(sys.executable)


class LazyCloneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.workspace = Path(self.temp_dir.name)
        self.config_dir = self.workspace / "config"
        self.prompt_dir = self.config_dir / "prompts"
        self.prompt_dir.mkdir(parents=True, exist_ok=True)
        self.invocation_log = self.workspace / "invocations.json"
        self.capture_script = self.workspace / "capture_invocation.py"
        self.capture_script.write_text(
            "\n".join([
                "import json, os, sys",
                "from pathlib import Path",
                "prompt_path = Path(sys.argv[1])",
                "log_path = Path(sys.argv[2])",
                "items = json.loads(log_path.read_text()) if log_path.exists() else []",
                "items.append({'cwd': os.getcwd(), 'files': sorted(os.listdir('.'))})",
                "log_path.write_text(json.dumps(items))",
            ]) + "\n",
            encoding="utf-8",
        )

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI_PYTHON), str(CLI_PATH), *args],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )

    def build_python_command(self, script_path: Path, *args: str) -> str:
        parts = [shlex.quote(str(CLI_PYTHON)), shlex.quote(str(script_path))]
        parts.extend(shlex.quote(arg) for arg in args)
        return " ".join(parts)

    def write_config(self, config_data: dict) -> Path:
        config_path = self.config_dir / "propagate.yaml"
        config_path.write_text(yaml.dump(config_data, sort_keys=False), encoding="utf-8")
        return config_path

    def _create_bare_repo(self, name: str) -> Path:
        bare_dir = self.workspace / name
        bare_dir.mkdir()
        subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True, capture_output=True)
        work_dir = self.workspace / f"{name}-work"
        work_dir.mkdir()
        subprocess.run(["git", "clone", str(bare_dir), str(work_dir)], check=True, capture_output=True)
        (work_dir / "README.md").write_text("init\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(work_dir), check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@test", "commit", "-m", "init"],
            cwd=str(work_dir), check=True, capture_output=True,
        )
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(work_dir), check=True, capture_output=True)
        shutil.rmtree(work_dir)
        return bare_dir

    def test_unused_url_repository_is_not_cloned(self) -> None:
        """A URL repo referenced only by an execution that never runs should not be cloned."""
        real_repo = self._create_bare_repo("real-repo")
        (self.prompt_dir / "task.md").write_text("task\n", encoding="utf-8")

        config_path = self.write_config({
            "version": "6",
            "agent": {
                "command": self.build_python_command(
                    self.capture_script,
                    "{prompt_file}",
                    str(self.invocation_log),
                )
            },
            "repositories": {
                "used": {"url": str(real_repo)},
                "unused": {"url": "/nonexistent/bad/url/that/should/never/be/cloned"},
            },
            "executions": {
                "run-this": {
                    "repository": "used",
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                },
                "never-runs": {
                    "repository": "unused",
                    "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                },
            },
        })

        result = self.run_cli("run", "--config", str(config_path), "--execution", "run-this")

        # Run succeeds — the bad URL repo was never cloned
        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        self.assertEqual(len(invocations), 1)
        cwd_path = Path(invocations[0]["cwd"])
        self.addCleanup(shutil.rmtree, cwd_path, True)
        self.assertIn("README.md", invocations[0]["files"])

    def test_url_repository_cloned_only_when_execution_runs(self) -> None:
        """Clone happens just before the execution that needs it, not at startup."""
        bare_repo = self._create_bare_repo("lazy-repo")
        (self.prompt_dir / "first.md").write_text("first\n", encoding="utf-8")
        (self.prompt_dir / "second.md").write_text("second\n", encoding="utf-8")

        local_dir = self.workspace / "local-repo"
        local_dir.mkdir()

        config_path = self.write_config({
            "version": "6",
            "agent": {
                "command": self.build_python_command(
                    self.capture_script,
                    "{prompt_file}",
                    str(self.invocation_log),
                )
            },
            "repositories": {
                "local": {"path": str(local_dir)},
                "remote": {"url": str(bare_repo)},
            },
            "executions": {
                "first": {
                    "repository": "local",
                    "sub_tasks": [{"id": "first", "prompt": "./prompts/first.md"}],
                },
                "second": {
                    "repository": "remote",
                    "sub_tasks": [{"id": "second", "prompt": "./prompts/second.md"}],
                },
            },
            "propagation": {
                "triggers": [
                    {"after": "first", "run": "second"},
                ]
            },
        })

        result = self.run_cli("run", "--config", str(config_path), "--execution", "first")

        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        self.assertEqual(len(invocations), 2)
        # First ran in local dir
        self.assertEqual(Path(invocations[0]["cwd"]).resolve(), local_dir.resolve())
        # Second ran in cloned dir (not the bare repo)
        second_cwd = Path(invocations[1]["cwd"])
        self.addCleanup(shutil.rmtree, second_cwd, True)
        self.assertNotEqual(second_cwd.resolve(), bare_repo.resolve())
        self.assertIn("README.md", invocations[1]["files"])
        # Clone log appears after first execution started
        stderr = result.stderr
        first_pos = stderr.find("Running execution 'first'")
        clone_pos = stderr.find("Cloning repository 'remote'")
        self.assertGreater(clone_pos, first_pos, "Clone should happen after first execution starts")
