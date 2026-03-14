from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from conftest import inject_test_repository

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "propagate.py"
CLI_PYTHON = REPO_ROOT / "venv" / "bin" / "python"
if not CLI_PYTHON.exists():
    CLI_PYTHON = Path(sys.executable)


class PropagateStage5SignalTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.workspace = Path(self.temp_dir.name)
        self.capture_script = self.workspace / "capture_prompt.py"
        self.capture_output = self.workspace / "agent-output.json"
        self.invocation_script = self.workspace / "append_prompt.py"
        self.invocation_log = self.workspace / "invocations.json"

        self.capture_script.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "import json",
                    "import sys",
                    "from pathlib import Path",
                    "",
                    "prompt_path = Path(sys.argv[1])",
                    "output_path = Path(sys.argv[2])",
                    "output_path.write_text(",
                    "    json.dumps(",
                    "        {",
                    '            "prompt_path": str(prompt_path),',
                    '            "content": prompt_path.read_text(encoding="utf-8"),',
                    "        }",
                    "    ),",
                    '    encoding="utf-8",',
                    ")",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.invocation_script.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "import json",
                    "import sys",
                    "from pathlib import Path",
                    "",
                    "prompt_path = Path(sys.argv[1])",
                    "log_path = Path(sys.argv[2])",
                    "items = []",
                    "if log_path.exists():",
                    "    items = json.loads(log_path.read_text(encoding='utf-8'))",
                    "items.append(prompt_path.read_text(encoding='utf-8'))",
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

    def write_config(self, config_data: dict[str, object], config_dir: Path | None = None) -> Path:
        config_root = config_dir or (self.workspace / "config")
        prompt_dir = config_root / "prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_root / "propagate.yaml"
        if "repositories" not in config_data:
            executions = config_data.get("executions")
            if isinstance(executions, dict):
                repositories, patched_executions = inject_test_repository(executions, self.workspace)
                config_data = {**config_data, "repositories": repositories, "executions": patched_executions}
        config_path.write_text(yaml.dump(config_data, sort_keys=False), encoding="utf-8")
        return config_path

    def test_signal_auto_selects_execution_and_populates_context(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Task prompt.\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "version": "6",
                "agent": {
                    "command": self.build_python_command(
                        self.capture_script,
                        "{prompt_file}",
                        str(self.capture_output),
                    )
                },
                "signals": {
                    "repo-change": {
                        "payload": {
                            "branch": {"type": "string", "required": True},
                            "files": {"type": "list"},
                            "urgent": {"type": "boolean"},
                        }
                    }
                },
                "executions": {
                    "build": {
                        "signals": ["repo-change"],
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            },
            config_dir,
        )

        result = self.run_cli(
            "run",
            "--config",
            str(config_path),
            "--signal",
            "repo-change",
            "--signal-payload",
            '{"branch":"main","files":["propagate.py"],"urgent":true}',
            cwd=self.workspace,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        captured_prompt = json.loads(self.capture_output.read_text(encoding="utf-8"))["content"]
        self.assertIn("### :signal.type\nrepo-change\n", captured_prompt)
        self.assertIn("### :signal.source\ncli\n", captured_prompt)
        self.assertIn("### :signal.branch\nmain\n", captured_prompt)
        self.assertIn("### :signal.files\n- propagate.py\n", captured_prompt)
        self.assertIn("### :signal.urgent\nTrue\n", captured_prompt)
        self.assertIn("### :signal.payload\nbranch: main\nfiles:\n- propagate.py\nurgent: true\n", captured_prompt)

        context_dir = config_dir / ".propagate-context" / "build"
        self.assertEqual((context_dir / ":signal.type").read_text(encoding="utf-8"), "repo-change")
        self.assertEqual((context_dir / ":signal.source").read_text(encoding="utf-8"), "cli")
        self.assertEqual((context_dir / ":signal.branch").read_text(encoding="utf-8"), "main")
        self.assertEqual((context_dir / ":signal.files").read_text(encoding="utf-8"), "- propagate.py\n")
        self.assertEqual((context_dir / ":signal.urgent").read_text(encoding="utf-8"), "True")

    def test_propagation_activates_follow_on_execution_once_when_duplicate_triggers_match(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "build.md").write_text("build prompt\n", encoding="utf-8")
        (prompt_dir / "verify.md").write_text("verify prompt\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "version": "6",
                "agent": {
                    "command": self.build_python_command(
                        self.invocation_script,
                        "{prompt_file}",
                        str(self.invocation_log),
                    )
                },
                "signals": {
                    "repo-change": {
                        "payload": {
                            "branch": {"type": "string", "required": True},
                        }
                    }
                },
                "executions": {
                    "build": {
                        "signals": ["repo-change"],
                        "sub_tasks": [{"id": "build", "prompt": "./prompts/build.md"}],
                    },
                    "verify": {
                        "sub_tasks": [{"id": "verify", "prompt": "./prompts/verify.md"}],
                    },
                },
                "propagation": {
                    "triggers": [
                        {"after": "build", "on_signal": "repo-change", "run": "verify"},
                        {"after": "build", "on_signal": "repo-change", "run": "verify"},
                    ]
                },
            },
            config_dir,
        )

        result = self.run_cli(
            "run",
            "--config",
            str(config_path),
            "--signal",
            "repo-change",
            "--signal-payload",
            '{"branch":"main"}',
            cwd=self.workspace,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.invocation_log.read_text(encoding="utf-8")),
            [
                "build prompt\n\n## Context\n\n### :signal.branch\nmain\n\n### :signal.payload\nbranch: main\n\n### :signal.source\ncli\n\n### :signal.type\nrepo-change\n",
                "verify prompt\n\n## Context\n\n### :signal.branch\nmain\n\n### :signal.payload\nbranch: main\n\n### :signal.source\ncli\n\n### :signal.type\nrepo-change\n",
            ],
        )
        self.assertIn("Skipping activation of 'verify' because it is already active.", result.stderr)

    def test_signal_validation_fails_before_execution(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Task prompt.\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "version": "6",
                "agent": {
                    "command": self.build_python_command(
                        self.capture_script,
                        "{prompt_file}",
                        str(self.capture_output),
                    )
                },
                "signals": {
                    "repo-change": {
                        "payload": {
                            "branch": {"type": "string", "required": True},
                        }
                    }
                },
                "executions": {
                    "build": {
                        "signals": ["repo-change"],
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            },
            config_dir,
        )

        result = self.run_cli(
            "run",
            "--config",
            str(config_path),
            "--signal",
            "repo-change",
            "--signal-payload",
            "{}",
            cwd=self.workspace,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Signal 'repo-change' payload is missing required field 'branch'.", result.stderr)
        self.assertFalse(self.capture_output.exists())

    def test_malformed_signal_payload_fails_before_execution(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Task prompt.\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "version": "6",
                "agent": {
                    "command": self.build_python_command(
                        self.capture_script,
                        "{prompt_file}",
                        str(self.capture_output),
                    )
                },
                "signals": {
                    "repo-change": {
                        "payload": {
                            "branch": {"type": "string", "required": True},
                        }
                    }
                },
                "executions": {
                    "build": {
                        "signals": ["repo-change"],
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            },
            config_dir,
        )

        result = self.run_cli(
            "run",
            "--config",
            str(config_path),
            "--signal",
            "repo-change",
            "--signal-payload",
            "{branch: [oops}",
            cwd=self.workspace,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Failed to parse Signal 'repo-change' payload:", result.stderr)
        self.assertFalse(self.capture_output.exists())

    def test_signal_required_execution_fails_without_signal_auto_select(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Task prompt.\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "version": "6",
                "agent": {
                    "command": self.build_python_command(
                        self.capture_script,
                        "{prompt_file}",
                        str(self.capture_output),
                    )
                },
                "signals": {
                    "run": {"payload": {}}
                },
                "executions": {
                    "deploy": {
                        "signals": ["run"],
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            },
            config_dir,
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("requires a signal", result.stderr)
        self.assertIn("run", result.stderr)

    def test_signal_required_execution_fails_without_signal_explicit_select(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Task prompt.\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "version": "6",
                "agent": {
                    "command": self.build_python_command(
                        self.capture_script,
                        "{prompt_file}",
                        str(self.capture_output),
                    )
                },
                "signals": {
                    "deploy": {"payload": {}}
                },
                "executions": {
                    "deploy-backend": {
                        "signals": ["deploy"],
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            },
            config_dir,
        )

        result = self.run_cli(
            "run", "--config", str(config_path), "--execution", "deploy-backend", cwd=self.workspace
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("requires a signal", result.stderr)
        self.assertIn("deploy", result.stderr)

    def test_invalid_propagation_trigger_fails_during_config_load(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Task prompt.\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "version": "6",
                "agent": {
                    "command": self.build_python_command(
                        self.capture_script,
                        "{prompt_file}",
                        str(self.capture_output),
                    )
                },
                "executions": {
                    "build": {
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
                "propagation": {
                    "triggers": [
                        {"after": "missing", "run": "build"},
                    ]
                },
            },
            config_dir,
        )

        result = self.run_cli(
            "run",
            "--config",
            str(config_path),
            cwd=self.workspace,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Propagation trigger #1.after references unknown execution 'missing'.", result.stderr)
        self.assertFalse(self.capture_output.exists())


if __name__ == "__main__":
    unittest.main()
