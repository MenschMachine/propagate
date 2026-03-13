from __future__ import annotations

import json
import shlex
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


class SubTaskWithoutPromptTests(unittest.TestCase):

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
        self.repo_dir = self.workspace / "repo"
        self.repo_dir.mkdir()

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
        config_path = self.config_dir / "propagate.yaml"
        config_path.write_text(yaml.dump(config_data, sort_keys=False), encoding="utf-8")
        return config_path

    def test_subtask_without_prompt_runs_hooks_but_no_agent(self) -> None:
        marker = self.workspace / "hook_ran.txt"
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
                    "repo": {"path": str(self.repo_dir)},
                },
                "executions": {
                    "setup": {
                        "repository": "repo",
                        "sub_tasks": [
                            {
                                "id": "hook-only",
                                "before": [f"touch {shlex.quote(str(marker))}"],
                            },
                        ],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "setup", cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(marker.exists(), "before hook should have run")
        self.assertFalse(self.invocation_log.exists(), "agent should not have been invoked")

    def test_subtask_empty_prompt_string_rejected(self) -> None:
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
                    "repo": {"path": str(self.repo_dir)},
                },
                "executions": {
                    "setup": {
                        "repository": "repo",
                        "sub_tasks": [
                            {"id": "bad", "prompt": ""},
                        ],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "setup", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("'prompt' must be a non-empty string when provided", result.stderr)

    def test_mixed_subtasks_with_and_without_prompt(self) -> None:
        (self.prompt_dir / "task.md").write_text("do the thing\n", encoding="utf-8")
        marker = self.workspace / "setup_ran.txt"
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
                    "repo": {"path": str(self.repo_dir)},
                },
                "executions": {
                    "pipeline": {
                        "repository": "repo",
                        "sub_tasks": [
                            {
                                "id": "setup",
                                "before": [f"touch {shlex.quote(str(marker))}"],
                            },
                            {
                                "id": "work",
                                "prompt": "./prompts/task.md",
                            },
                        ],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "pipeline", cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(marker.exists(), "setup hook should have run")
        self.assertTrue(self.invocation_log.exists(), "agent should have been invoked for 'work' sub-task")
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        self.assertEqual(len(invocations), 1)


if __name__ == "__main__":
    unittest.main()
