from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "propagate.py"
CLI_PYTHON = REPO_ROOT / "venv" / "bin" / "python"
if not CLI_PYTHON.exists():
    CLI_PYTHON = Path(sys.executable)


class PropagateStage2CLITests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.workspace = Path(self.temp_dir.name)
        self.capture_script = self.workspace / "capture_prompt.py"
        self.capture_output = self.workspace / "agent-output.json"
        self.invocation_script = self.workspace / "append_prompt.py"
        self.invocation_log = self.workspace / "invocations.json"
        self.hook_script = self.workspace / "record_hook.py"
        self.hook_log = self.workspace / "hook-log.json"
        self.context_source_script = self.workspace / "emit_context.py"
        self.fail_agent_script = self.workspace / "fail_agent.py"
        self.fail_agent_log = self.workspace / "failed-agent-prompts.json"
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
                    '            "exists_during_run": prompt_path.exists(),',
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
        self.hook_script.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "import json",
                    "import sys",
                    "from pathlib import Path",
                    "",
                    "log_path = Path(sys.argv[1])",
                    "label = sys.argv[2]",
                    "exit_code = int(sys.argv[3])",
                    "items = []",
                    "if log_path.exists():",
                    "    items = json.loads(log_path.read_text(encoding='utf-8'))",
                    "items.append(label)",
                    "log_path.write_text(json.dumps(items), encoding='utf-8')",
                    "raise SystemExit(exit_code)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.fail_agent_script.write_text(
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
                    "raise SystemExit(1)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.context_source_script.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "import sys",
                    "",
                    "sys.stdout.write(sys.argv[1])",
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

    def write_config(
        self,
        executions: dict[str, object],
        config_dir: Path,
        context_sources: dict[str, object] | None = None,
        agent_command: str | None = None,
    ) -> Path:
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "propagate.yaml"
        command = agent_command or " ".join(
            [
                shlex.quote(str(CLI_PYTHON)),
                shlex.quote(str(self.capture_script)),
                "{prompt_file}",
                shlex.quote(str(self.capture_output)),
            ]
        )
        config_data: dict[str, object] = {
            "version": "6",
            "agent": {"command": command},
            "executions": executions,
        }
        if context_sources is not None:
            config_data["context_sources"] = context_sources
        config_path.write_text(
            self.to_yaml(config_data),
            encoding="utf-8",
        )
        return config_path

    def build_python_command(self, script_path: Path, *args: str) -> str:
        parts = [shlex.quote(str(CLI_PYTHON)), shlex.quote(str(script_path))]
        parts.extend(shlex.quote(arg) for arg in args)
        return " ".join(parts)

    def to_yaml(self, value: object, indent: int = 0) -> str:
        prefix = " " * indent
        if isinstance(value, dict):
            lines: list[str] = []
            for key, nested_value in value.items():
                if isinstance(nested_value, (dict, list)):
                    lines.append(f"{prefix}{key}:")
                    lines.append(self.to_yaml(nested_value, indent + 2).rstrip("\n"))
                else:
                    lines.append(f"{prefix}{key}: {json.dumps(nested_value)}")
            return "\n".join(lines) + "\n"
        if isinstance(value, list):
            lines = []
            for item in value:
                if isinstance(item, dict):
                    item_lines = self.to_yaml(item, indent + 2).rstrip("\n").splitlines()
                    lines.append(f"{prefix}- {item_lines[0].lstrip()}")
                    lines.extend(item_lines[1:])
                elif isinstance(item, list):
                    lines.append(f"{prefix}-")
                    lines.append(self.to_yaml(item, indent + 2).rstrip("\n"))
                else:
                    lines.append(f"{prefix}- {json.dumps(item)}")
            return "\n".join(lines) + "\n"
        return f"{prefix}{json.dumps(value)}\n"

    def read_capture(self) -> dict[str, object]:
        return json.loads(self.capture_output.read_text(encoding="utf-8"))

    def test_run_with_single_execution_resolves_prompt_relative_to_config_and_cleans_temp_file(self) -> None:
        config_dir = self.workspace / "nested" / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        prompt_path = prompt_dir / "task.md"
        prompt_text = "# Task\n\nUse the nested prompt.\n"
        prompt_path.write_text(prompt_text, encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                        }
                    ]
                }
            },
            config_dir,
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        capture = self.read_capture()
        self.assertEqual(capture["content"], prompt_text)
        self.assertTrue(capture["exists_during_run"])
        self.assertTrue(Path(capture["prompt_path"]).name.startswith("propagate-"))
        self.assertFalse(Path(capture["prompt_path"]).exists())
        self.assertFalse((self.workspace / ".propagate-context").exists())

    def test_run_with_execution_option_selects_requested_execution(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "first.md").write_text("first prompt\n", encoding="utf-8")
        chosen_prompt = "second prompt\n"
        (prompt_dir / "second.md").write_text(chosen_prompt, encoding="utf-8")

        config_path = self.write_config(
            {
                "first": {"sub_tasks": [{"id": "task", "prompt": "./prompts/first.md"}]},
                "second": {"sub_tasks": [{"id": "task", "prompt": "./prompts/second.md"}]},
            },
            config_dir,
        )

        result = self.run_cli(
            "run",
            "--config",
            str(config_path),
            "--execution",
            "second",
            cwd=self.workspace,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_capture()["content"], chosen_prompt)

    def test_run_requires_execution_when_config_has_multiple_executions(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "first.md").write_text("first\n", encoding="utf-8")
        (prompt_dir / "second.md").write_text("second\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "first": {"sub_tasks": [{"id": "task", "prompt": "./prompts/first.md"}]},
                "second": {"sub_tasks": [{"id": "task", "prompt": "./prompts/second.md"}]},
            },
            config_dir,
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("specify one with --execution", result.stderr)
        self.assertFalse(self.capture_output.exists())

    def test_context_set_writes_file_and_get_returns_exact_value(self) -> None:
        value = "line 1\nline 2 with spaces"

        set_result = self.run_cli("context", "set", "topic", value, cwd=self.workspace)

        self.assertEqual(set_result.returncode, 0, set_result.stderr)
        context_path = self.workspace / ".propagate-context" / "topic"
        self.assertEqual(context_path.read_text(encoding="utf-8"), value)

        get_result = self.run_cli("context", "get", "topic", cwd=self.workspace)

        self.assertEqual(get_result.returncode, 0, get_result.stderr)
        self.assertEqual(get_result.stdout, value)
        self.assertNotIn(value, get_result.stderr)

    def test_context_commands_fail_clearly_for_invalid_and_missing_keys(self) -> None:
        invalid_result = self.run_cli("context", "set", "bad/key", "value", cwd=self.workspace)

        self.assertEqual(invalid_result.returncode, 1)
        self.assertIn("Invalid context key 'bad/key'.", invalid_result.stderr)

        (self.workspace / ".propagate-context").mkdir()
        missing_result = self.run_cli("context", "get", "missing", cwd=self.workspace)

        self.assertEqual(missing_result.returncode, 1)
        self.assertIn("Context key 'missing' was not found", missing_result.stderr)

    def test_run_appends_sorted_context_section(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        prompt_path = prompt_dir / "task.md"
        prompt_path.write_text("Base prompt.", encoding="utf-8")
        context_dir = self.workspace / ".propagate-context"
        context_dir.mkdir()
        (context_dir / "zeta").write_text("last value", encoding="utf-8")
        (context_dir / "alpha").write_text("first value", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                        }
                    ]
                }
            },
            config_dir,
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.read_capture()["content"],
            "Base prompt.\n\n## Context\n\n### alpha\nfirst value\n\n### zeta\nlast value\n",
        )

    def test_run_executes_sub_tasks_sequentially(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "first.md").write_text("first\n", encoding="utf-8")
        (prompt_dir / "second.md").write_text("second\n", encoding="utf-8")

        config_path = config_dir / "propagate.yaml"
        command = " ".join(
            [
                shlex.quote(str(CLI_PYTHON)),
                shlex.quote(str(self.invocation_script)),
                "{prompt_file}",
                shlex.quote(str(self.invocation_log)),
            ]
        )
        config_path.write_text(
            self.to_yaml(
                {
                    "version": "6",
                    "agent": {"command": command},
                    "executions": {
                        "default": {
                            "sub_tasks": [
                                {"id": "first", "prompt": "./prompts/first.md"},
                                {"id": "second", "prompt": "./prompts/second.md"},
                            ]
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.invocation_log.read_text(encoding="utf-8")),
            ["first\n", "second\n"],
        )

    def test_run_with_empty_prompt_places_context_section_at_top(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("", encoding="utf-8")
        context_dir = self.workspace / ".propagate-context"
        context_dir.mkdir()
        (context_dir / "topic").write_text("value", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                        }
                    ]
                }
            },
            config_dir,
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.read_capture()["content"],
            "## Context\n\n### topic\nvalue\n",
        )

    def test_run_before_hook_loads_context_source_into_reserved_key(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Prompt body.\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                            "before": [":spec"],
                        }
                    ]
                }
            },
            config_dir,
            context_sources={
                "spec": {
                    "command": self.build_python_command(
                        self.context_source_script,
                        "line 1\nline 2",
                    )
                }
            },
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.read_capture()["content"],
            "Prompt body.\n\n## Context\n\n### :spec\nline 1\nline 2\n",
        )
        self.assertEqual(
            (self.workspace / ".propagate-context" / ":spec").read_text(encoding="utf-8"),
            "line 1\nline 2",
        )

    def test_after_hook_context_source_does_not_change_current_prompt_but_updates_later_sub_tasks(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "first.md").write_text("First prompt.\n", encoding="utf-8")
        (prompt_dir / "second.md").write_text("Second prompt.\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "first",
                            "prompt": "./prompts/first.md",
                            "after": [":late"],
                        },
                        {
                            "id": "second",
                            "prompt": "./prompts/second.md",
                        },
                    ]
                }
            },
            config_dir,
            context_sources={
                "late": {
                    "command": self.build_python_command(
                        self.context_source_script,
                        "after-hook context",
                    )
                }
            },
            agent_command=self.build_python_command(
                self.invocation_script,
                "{prompt_file}",
                str(self.invocation_log),
            ),
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.invocation_log.read_text(encoding="utf-8")),
            [
                "First prompt.\n",
                "Second prompt.\n\n## Context\n\n### :late\nafter-hook context\n",
            ],
        )
        self.assertEqual(
            (self.workspace / ".propagate-context" / ":late").read_text(encoding="utf-8"),
            "after-hook context",
        )

    def test_context_source_failure_runs_on_failure_and_reports_source_name(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Prompt\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                            "before": [":broken"],
                            "on_failure": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "cleanup", "0")
                            ],
                        }
                    ]
                }
            },
            config_dir,
            context_sources={
                "broken": {
                    "command": self.build_python_command(
                        self.hook_script,
                        str(self.hook_log),
                        "source-fail",
                        "1",
                    )
                }
            },
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Context source 'broken' failed for sub-task 'task' with exit code 1.", result.stderr)
        self.assertEqual(
            json.loads(self.hook_log.read_text(encoding="utf-8")),
            ["source-fail", "cleanup"],
        )
        self.assertFalse(self.capture_output.exists())

    def test_after_hook_failure_runs_on_failure_and_aborts_remaining_after_hooks(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Prompt\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                            "before": [self.build_python_command(self.hook_script, str(self.hook_log), "before", "0")],
                            "after": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "after-fail", "1"),
                                self.build_python_command(self.hook_script, str(self.hook_log), "after-skipped", "0"),
                            ],
                            "on_failure": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "cleanup", "0")
                            ],
                        }
                    ]
                }
            },
            config_dir,
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("After hook #1 failed for sub-task 'task' with exit code 1.", result.stderr)
        self.assertEqual(
            json.loads(self.hook_log.read_text(encoding="utf-8")),
            ["before", "after-fail", "cleanup"],
        )
        self.assertTrue(self.capture_output.exists())

    def test_before_hook_failure_runs_on_failure_and_skips_agent_and_after(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Prompt\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                            "before": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "before-ok", "0"),
                                self.build_python_command(self.hook_script, str(self.hook_log), "before-fail", "1"),
                                self.build_python_command(self.hook_script, str(self.hook_log), "before-skipped", "0"),
                            ],
                            "after": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "after-skipped", "0")
                            ],
                            "on_failure": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "cleanup", "0")
                            ],
                        }
                    ]
                }
            },
            config_dir,
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Before hook #2 failed for sub-task 'task' with exit code 1.", result.stderr)
        self.assertEqual(
            json.loads(self.hook_log.read_text(encoding="utf-8")),
            ["before-ok", "before-fail", "cleanup"],
        )
        self.assertFalse(self.capture_output.exists())

    def test_agent_failure_runs_on_failure_and_skips_after_hooks(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Prompt\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                            "after": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "after-skipped", "0")
                            ],
                            "on_failure": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "cleanup", "0")
                            ],
                        }
                    ]
                }
            },
            config_dir,
            agent_command=self.build_python_command(
                self.fail_agent_script,
                "{prompt_file}",
                str(self.fail_agent_log),
            ),
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Agent command failed for sub-task 'task' with exit code 1.", result.stderr)
        self.assertEqual(
            json.loads(self.fail_agent_log.read_text(encoding="utf-8")),
            ["Prompt\n"],
        )
        self.assertEqual(
            json.loads(self.hook_log.read_text(encoding="utf-8")),
            ["cleanup"],
        )

    def test_success_path_does_not_run_on_failure_hooks(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Prompt\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                            "before": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "before", "0")
                            ],
                            "after": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "after", "0")
                            ],
                            "on_failure": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "cleanup", "0")
                            ],
                        }
                    ]
                }
            },
            config_dir,
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.hook_log.read_text(encoding="utf-8")),
            ["before", "after"],
        )

    def test_later_sub_tasks_see_context_values_from_earlier_hooks(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "first.md").write_text("First prompt.\n", encoding="utf-8")
        (prompt_dir / "second.md").write_text("Second prompt.\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "first",
                            "prompt": "./prompts/first.md",
                            "before": [":shared"],
                        },
                        {
                            "id": "second",
                            "prompt": "./prompts/second.md",
                        },
                    ]
                }
            },
            config_dir,
            context_sources={
                "shared": {
                    "command": self.build_python_command(
                        self.context_source_script,
                        "shared context",
                    )
                }
            },
            agent_command=self.build_python_command(
                self.invocation_script,
                "{prompt_file}",
                str(self.invocation_log),
            ),
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.invocation_log.read_text(encoding="utf-8")),
            [
                "First prompt.\n\n## Context\n\n### :shared\nshared context\n",
                "Second prompt.\n\n## Context\n\n### :shared\nshared context\n",
            ],
        )
        self.assertEqual(
            (self.workspace / ".propagate-context" / ":shared").read_text(encoding="utf-8"),
            "shared context",
        )

    def test_on_failure_hook_failure_is_reported_with_original_error(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Prompt\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                            "before": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "before-fail", "1")
                            ],
                            "on_failure": [
                                self.build_python_command(self.hook_script, str(self.hook_log), "cleanup-fail", "1")
                            ],
                        }
                    ]
                }
            },
            config_dir,
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Before hook #1 failed for sub-task 'task' with exit code 1", result.stderr)
        self.assertIn("on_failure hook #1 failed for sub-task 'task' with exit code 1.", result.stderr)
        self.assertEqual(
            json.loads(self.hook_log.read_text(encoding="utf-8")),
            ["before-fail", "cleanup-fail"],
        )

    def test_unknown_context_source_reference_fails_during_config_validation(self) -> None:
        config_dir = self.workspace / "config"
        prompt_dir = config_dir / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "task.md").write_text("Prompt\n", encoding="utf-8")

        config_path = self.write_config(
            {
                "default": {
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                            "before": [":missing"],
                        }
                    ]
                }
            },
            config_dir,
        )

        result = self.run_cli("run", "--config", str(config_path), cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("references unknown context source 'missing'", result.stderr)


if __name__ == "__main__":
    unittest.main()
