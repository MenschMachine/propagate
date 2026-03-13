from __future__ import annotations

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


class DuplicateSubTaskIdTests(unittest.TestCase):

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

    def test_duplicate_subtask_id_fails_during_config_load(self) -> None:
        (self.prompt_dir / "task.md").write_text("task\n", encoding="utf-8")
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
                    "docs": {"path": "../docs"},
                },
                "executions": {
                    "update-docs": {
                        "repository": "docs",
                        "sub_tasks": [
                            {"id": "task", "prompt": "./prompts/task.md"},
                            {"id": "task", "prompt": "./prompts/task.md"},
                        ],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "update-docs", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Execution 'update-docs' contains duplicate sub-task id 'task'.", result.stderr)
        self.assertFalse(self.invocation_log.exists())


if __name__ == "__main__":
    unittest.main()
