from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from propagate_app.run_state import load_run_state, state_file_path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "propagate.py"
CLI_PYTHON = REPO_ROOT / "venv" / "bin" / "python"
if not CLI_PYTHON.exists():
    CLI_PYTHON = Path(sys.executable)


class TaskResumeTests(unittest.TestCase):
    maxDiff = None

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
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "import json",
                    "import os",
                    "import sys",
                    "from pathlib import Path",
                    "",
                    "prompt_path = Path(sys.argv[1])",
                    "log_path = Path(sys.argv[2])",
                    "items = []",
                    "if log_path.exists():",
                    "    items = json.loads(log_path.read_text(encoding='utf-8'))",
                    "items.append({",
                    "    'cwd': os.getcwd(),",
                    "    'prompt': prompt_path.read_text(encoding='utf-8'),",
                    "    'files': sorted(os.listdir('.')),",
                    "})",
                    "log_path.write_text(json.dumps(items), encoding='utf-8')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.fail_script = self.workspace / "fail_invocation.py"
        self.fail_script.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "import json",
                    "import os",
                    "import sys",
                    "from pathlib import Path",
                    "",
                    "prompt_path = Path(sys.argv[1])",
                    "log_path = Path(sys.argv[2])",
                    "fail_on = Path(sys.argv[3]).read_text(encoding='utf-8').strip()",
                    "items = []",
                    "if log_path.exists():",
                    "    items = json.loads(log_path.read_text(encoding='utf-8'))",
                    "current_prompt = prompt_path.read_text(encoding='utf-8')",
                    "items.append({",
                    "    'cwd': os.getcwd(),",
                    "    'prompt': current_prompt,",
                    "})",
                    "log_path.write_text(json.dumps(items), encoding='utf-8')",
                    "if current_prompt.strip() == fail_on:",
                    "    sys.exit(1)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def run_cli(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI_PYTHON), str(CLI_PATH), *args],
            cwd=cwd or self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )

    def build_python_command(self, script_path: Path, *args: str) -> str:
        parts = [shlex.quote(str(CLI_PYTHON)), shlex.quote(str(script_path))]
        parts.extend(shlex.quote(arg) for arg in args)
        return " ".join(parts)

    def write_config(self, config_data: dict[str, object]) -> Path:
        config_path = self.config_dir / f"{self._testMethodName}.yaml"
        config_path.write_text(yaml.dump(config_data, sort_keys=False), encoding="utf-8")
        return config_path

    def test_resume_skips_completed_tasks(self) -> None:
        """Execution with 3 tasks, fails on task 2. Resume skips task 1, runs tasks 2-3."""
        repo_dir = self.workspace / "repo"
        repo_dir.mkdir()
        (self.prompt_dir / "t1.md").write_text("task-1\n", encoding="utf-8")
        (self.prompt_dir / "t2.md").write_text("task-2\n", encoding="utf-8")
        (self.prompt_dir / "t3.md").write_text("task-3\n", encoding="utf-8")

        fail_on_file = self.workspace / "fail_on.txt"
        fail_on_file.write_text("task-2", encoding="utf-8")

        config_path = self.write_config(
            {
                "version": "6",
                "agent": {
                    "command": self.build_python_command(
                        self.fail_script,
                        "{prompt_file}",
                        str(self.invocation_log),
                        str(fail_on_file),
                    )
                },
                "repositories": {
                    "repo": {"path": "../repo"},
                },
                "executions": {
                    "work": {
                        "repository": "repo",
                        "sub_tasks": [
                            {"id": "t1", "prompt": "./prompts/t1.md"},
                            {"id": "t2", "prompt": "./prompts/t2.md"},
                            {"id": "t3", "prompt": "./prompts/t3.md"},
                        ],
                    },
                },
            }
        )

        # First run: t1 succeeds, t2 fails
        result = self.run_cli("run", "--config", str(config_path), "--execution", "work")
        self.assertEqual(result.returncode, 1)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        prompts = [inv["prompt"].strip() for inv in invocations]
        self.assertEqual(prompts, ["task-1", "task-2"])

        # Fix failure and resume
        fail_on_file.write_text("never", encoding="utf-8")
        self.invocation_log.unlink()

        result = self.run_cli("run", "--config", str(config_path), "--resume")
        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        prompts = [inv["prompt"].strip() for inv in invocations]
        # t1 should be skipped, only t2 and t3 run
        self.assertEqual(prompts, ["task-2", "task-3"])

    def test_state_file_contains_completed_tasks(self) -> None:
        """After partial failure, verify YAML state contains the right completed task IDs."""
        repo_dir = self.workspace / "repo"
        repo_dir.mkdir()
        (self.prompt_dir / "a.md").write_text("task-a\n", encoding="utf-8")
        (self.prompt_dir / "b.md").write_text("task-b\n", encoding="utf-8")

        fail_on_file = self.workspace / "fail_on.txt"
        fail_on_file.write_text("task-b", encoding="utf-8")

        config_path = self.write_config(
            {
                "version": "6",
                "agent": {
                    "command": self.build_python_command(
                        self.fail_script,
                        "{prompt_file}",
                        str(self.invocation_log),
                        str(fail_on_file),
                    )
                },
                "repositories": {
                    "repo": {"path": "../repo"},
                },
                "executions": {
                    "work": {
                        "repository": "repo",
                        "sub_tasks": [
                            {"id": "task-a", "prompt": "./prompts/a.md"},
                            {"id": "task-b", "prompt": "./prompts/b.md"},
                        ],
                    },
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "work")
        self.assertEqual(result.returncode, 1)

        state_file = state_file_path(config_path)
        self.assertTrue(state_file.exists())
        state_data = yaml.safe_load(state_file.read_text(encoding="utf-8"))
        self.assertIn("completed_tasks", state_data)
        self.assertEqual(state_data["completed_tasks"], {"work": ["task-a"]})

    def test_multi_execution_partial_resume(self) -> None:
        """Execution A completes fully, Execution B fails on task 2. Resume skips A entirely, skips B's task 1."""
        repo_dir = self.workspace / "repo"
        repo_dir.mkdir()
        (self.prompt_dir / "a1.md").write_text("a-task-1\n", encoding="utf-8")
        (self.prompt_dir / "b1.md").write_text("b-task-1\n", encoding="utf-8")
        (self.prompt_dir / "b2.md").write_text("b-task-2\n", encoding="utf-8")
        (self.prompt_dir / "b3.md").write_text("b-task-3\n", encoding="utf-8")

        fail_on_file = self.workspace / "fail_on.txt"
        fail_on_file.write_text("b-task-2", encoding="utf-8")

        config_path = self.write_config(
            {
                "version": "6",
                "agent": {
                    "command": self.build_python_command(
                        self.fail_script,
                        "{prompt_file}",
                        str(self.invocation_log),
                        str(fail_on_file),
                    )
                },
                "repositories": {
                    "repo": {"path": "../repo"},
                },
                "executions": {
                    "exec-a": {
                        "repository": "repo",
                        "sub_tasks": [
                            {"id": "a1", "prompt": "./prompts/a1.md"},
                        ],
                    },
                    "exec-b": {
                        "repository": "repo",
                        "depends_on": ["exec-a"],
                        "sub_tasks": [
                            {"id": "b1", "prompt": "./prompts/b1.md"},
                            {"id": "b2", "prompt": "./prompts/b2.md"},
                            {"id": "b3", "prompt": "./prompts/b3.md"},
                        ],
                    },
                },
            }
        )

        # First run: exec-a completes, exec-b fails on b2
        result = self.run_cli("run", "--config", str(config_path), "--execution", "exec-b")
        self.assertEqual(result.returncode, 1)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        prompts = [inv["prompt"].strip() for inv in invocations]
        self.assertEqual(prompts, ["a-task-1", "b-task-1", "b-task-2"])

        # Fix and resume
        fail_on_file.write_text("never", encoding="utf-8")
        self.invocation_log.unlink()

        result = self.run_cli("run", "--config", str(config_path), "--resume")
        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        prompts = [inv["prompt"].strip() for inv in invocations]
        # exec-a skipped entirely (completed_names), exec-b skips b1 (completed_tasks), runs b2 and b3
        self.assertEqual(prompts, ["b-task-2", "b-task-3"])

    def test_backward_compat_old_state_file(self) -> None:
        """Old state file without completed_tasks key loads without error."""
        repo_dir = self.workspace / "repo"
        repo_dir.mkdir()
        (self.prompt_dir / "x.md").write_text("x-task\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "version": "6",
                "agent": {
                    "command": self.build_python_command(
                        self.capture_script,
                        "{prompt_file}",
                        str(self.invocation_log),
                    )
                },
                "repositories": {
                    "repo": {"path": "../repo"},
                },
                "executions": {
                    "only": {
                        "repository": "repo",
                        "sub_tasks": [
                            {"id": "x", "prompt": "./prompts/x.md"},
                        ],
                    },
                },
            }
        )

        # Manually write an old-format state file (no completed_tasks key)
        state_file = state_file_path(config_path)
        state_data = {
            "config_path": str(config_path),
            "initial_execution": "only",
            "active_names": ["only"],
            "completed_names": [],
            "cloned_repos": {},
            "initialized_signal_context_dirs": [],
        }
        state_file.write_text(yaml.dump(state_data, default_flow_style=False), encoding="utf-8")

        # load_run_state should not raise
        run_state = load_run_state(config_path)
        self.assertEqual(run_state.schedule.completed_tasks, {})

        # Resume should work
        result = self.run_cli("run", "--config", str(config_path), "--resume")
        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        self.assertEqual(len(invocations), 1)
