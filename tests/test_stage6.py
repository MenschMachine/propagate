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


class PropagateStage6DagTests(unittest.TestCase):
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
                else:
                    lines.append(f"{prefix}- {json.dumps(item)}")
            return "\n".join(lines) + "\n"
        return f"{prefix}{json.dumps(value)}\n"

    def write_config(self, config_data: dict[str, object]) -> Path:
        config_path = self.config_dir / "propagate.yaml"
        config_path.write_text(self.to_yaml(config_data), encoding="utf-8")
        return config_path

    def test_repository_paths_normalize_absolute_paths(self) -> None:
        absolute_repo_dir = self.workspace / "absolute-docs"
        absolute_repo_dir.mkdir()
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
                    "absolute-docs": {
                        "path": str((absolute_repo_dir / ".." / "absolute-docs").absolute()),
                    },
                },
                "executions": {
                    "task": {
                        "repository": "absolute-docs",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "task", cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        self.assertEqual(len(invocations), 1)
        self.assertEqual(Path(invocations[0]["cwd"]).resolve(), absolute_repo_dir.resolve())
        self.assertIn(
            f"Routing execution 'task' to repository 'absolute-docs' at '{absolute_repo_dir.resolve()}'.",
            result.stderr,
        )
        self.assertNotIn("/../", result.stderr)

    def test_run_routes_executions_to_repositories_and_schedules_dependencies_in_config_order(self) -> None:
        core_dir = self.workspace / "core"
        docs_dir = self.workspace / "docs"
        core_dir.mkdir()
        docs_dir.mkdir()
        (core_dir / ".propagate-context").mkdir()
        (docs_dir / ".propagate-context").mkdir()
        (core_dir / ".propagate-context" / ":signal.type").write_text("stale-core", encoding="utf-8")
        (docs_dir / ".propagate-context" / ":signal.type").write_text("stale-docs", encoding="utf-8")

        (self.prompt_dir / "build-core.md").write_text("build core\n", encoding="utf-8")
        (self.prompt_dir / "prepare-docs.md").write_text("prepare docs\n", encoding="utf-8")
        (self.prompt_dir / "lint-docs.md").write_text("lint docs\n", encoding="utf-8")
        (self.prompt_dir / "update-docs.md").write_text("update docs\n", encoding="utf-8")

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
                    "core": {"path": "../core"},
                    "docs": {"path": "../docs"},
                },
                "signals": {
                    "repo-change": {
                        "payload": {
                            "branch": {"type": "string", "required": True},
                        }
                    }
                },
                "executions": {
                    "build-core": {
                        "repository": "core",
                        "signals": ["repo-change"],
                        "sub_tasks": [{"id": "build", "prompt": "./prompts/build-core.md"}],
                    },
                    "prepare-docs-context": {
                        "repository": "docs",
                        "sub_tasks": [{"id": "prepare", "prompt": "./prompts/prepare-docs.md"}],
                    },
                    "lint-docs": {
                        "repository": "docs",
                        "sub_tasks": [{"id": "lint", "prompt": "./prompts/lint-docs.md"}],
                    },
                    "update-docs": {
                        "repository": "docs",
                        "depends_on": ["prepare-docs-context", "lint-docs"],
                        "sub_tasks": [{"id": "update", "prompt": "./prompts/update-docs.md"}],
                    },
                },
                "propagation": {
                    "triggers": [
                        {"after": "build-core", "on_signal": "repo-change", "run": "update-docs"},
                    ]
                },
            }
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
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        self.assertEqual(
            [(Path(item["cwd"]).name, item["prompt"].splitlines()[0]) for item in invocations],
            [
                ("core", "build core"),
                ("docs", "prepare docs"),
                ("docs", "lint docs"),
                ("docs", "update docs"),
            ],
        )
        self.assertIn("Multiple runnable executions available (prepare-docs-context, lint-docs); selecting 'prepare-docs-context' by config order.", result.stderr)
        self.assertIn("Activating dependency 'prepare-docs-context' for execution 'update-docs'.", result.stderr)
        self.assertIn("Activating dependency 'lint-docs' for execution 'update-docs'.", result.stderr)
        self.assertEqual(
            (core_dir / ".propagate-context" / ":signal.type").read_text(encoding="utf-8"),
            "repo-change",
        )
        self.assertEqual(
            (docs_dir / ".propagate-context" / ":signal.type").read_text(encoding="utf-8"),
            "repo-change",
        )

    def test_cycle_detection_uses_combined_dependency_and_trigger_graph(self) -> None:
        repo_dir = self.workspace / "repo"
        repo_dir.mkdir()
        (self.prompt_dir / "a.md").write_text("a\n", encoding="utf-8")
        (self.prompt_dir / "b.md").write_text("b\n", encoding="utf-8")
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
                    "a": {
                        "repository": "repo",
                        "depends_on": ["b"],
                        "sub_tasks": [{"id": "a", "prompt": "./prompts/a.md"}],
                    },
                    "b": {
                        "repository": "repo",
                        "sub_tasks": [{"id": "b", "prompt": "./prompts/b.md"}],
                    },
                },
                "propagation": {
                    "triggers": [
                        {"after": "a", "run": "b"},
                    ]
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "a", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Execution graph contains a cycle: a -> b -> a.", result.stderr)

    def test_unknown_repository_reference_fails_during_config_load(self) -> None:
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
                        "repository": "missing",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "update-docs", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Execution 'update-docs' references unknown repository 'missing'.", result.stderr)
        self.assertFalse(self.invocation_log.exists())

    def test_unknown_dependency_reference_fails_during_config_load(self) -> None:
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
                        "depends_on": ["prepare-docs-context"],
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "update-docs", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "Execution 'update-docs' depends_on references unknown execution 'prepare-docs-context'.",
            result.stderr,
        )
        self.assertFalse(self.invocation_log.exists())

    def test_missing_repository_working_directory_fails_before_execution_starts(self) -> None:
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
                    "docs": {"path": "../missing-docs"},
                },
                "executions": {
                    "update-docs": {
                        "repository": "docs",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "update-docs", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Execution 'update-docs' cannot start in repository 'docs': working directory does not exist:", result.stderr)
        self.assertFalse(self.invocation_log.exists())

    def test_execution_without_repository_fails_during_config_load(self) -> None:
        (self.prompt_dir / "local.md").write_text("local task\n", encoding="utf-8")
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
                    "local-task": {
                        "sub_tasks": [{"id": "local", "prompt": "./prompts/local.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "local-task", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Execution 'local-task' must declare a 'repository'.", result.stderr)
        self.assertFalse(self.invocation_log.exists())

    def test_repository_working_directory_must_be_a_directory(self) -> None:
        docs_file = self.workspace / "docs-file"
        docs_file.write_text("not a directory\n", encoding="utf-8")
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
                    "docs": {"path": "../docs-file"},
                },
                "executions": {
                    "update-docs": {
                        "repository": "docs",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "update-docs", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "Execution 'update-docs' cannot start in repository 'docs': working directory is not a directory:",
            result.stderr,
        )
        self.assertFalse(self.invocation_log.exists())

    def test_signal_context_is_scoped_and_cleared_per_working_directory_during_dag_run(self) -> None:
        local_dir = self.workspace / "local"
        core_dir = self.workspace / "core"
        docs_dir = self.workspace / "docs"
        local_dir.mkdir()
        core_dir.mkdir()
        docs_dir.mkdir()

        local_context_dir = local_dir / ".propagate-context"
        core_context_dir = core_dir / ".propagate-context"
        docs_context_dir = docs_dir / ".propagate-context"
        local_context_dir.mkdir()
        core_context_dir.mkdir()
        docs_context_dir.mkdir()

        for context_dir, stale_value in (
            (local_context_dir, "stale-local"),
            (core_context_dir, "stale-core"),
            (docs_context_dir, "stale-docs"),
        ):
            (context_dir / ":signal.type").write_text(stale_value, encoding="utf-8")
            (context_dir / ":signal.legacy").write_text("remove-me", encoding="utf-8")
            (context_dir / "shared").write_text("keep-me", encoding="utf-8")

        (self.prompt_dir / "start.md").write_text("start prompt\n", encoding="utf-8")
        (self.prompt_dir / "build-core.md").write_text("build core\n", encoding="utf-8")
        (self.prompt_dir / "update-docs.md").write_text("update docs\n", encoding="utf-8")
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
                    "local": {"path": "../local"},
                    "core": {"path": "../core"},
                    "docs": {"path": "../docs"},
                },
                "signals": {
                    "repo-change": {
                        "payload": {
                            "branch": {"type": "string", "required": True},
                        }
                    }
                },
                "executions": {
                    "start-local": {
                        "repository": "local",
                        "signals": ["repo-change"],
                        "sub_tasks": [{"id": "start", "prompt": "./prompts/start.md"}],
                    },
                    "build-core": {
                        "repository": "core",
                        "sub_tasks": [{"id": "build", "prompt": "./prompts/build-core.md"}],
                    },
                    "update-docs": {
                        "repository": "docs",
                        "depends_on": ["build-core"],
                        "sub_tasks": [{"id": "update", "prompt": "./prompts/update-docs.md"}],
                    },
                },
                "propagation": {
                    "triggers": [
                        {"after": "start-local", "on_signal": "repo-change", "run": "update-docs"},
                    ]
                },
            }
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
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        self.assertEqual(
            [(Path(item["cwd"]).resolve(), item["prompt"].splitlines()[0]) for item in invocations],
            [
                (local_dir.resolve(), "start prompt"),
                (core_dir.resolve(), "build core"),
                (docs_dir.resolve(), "update docs"),
            ],
        )
        for invocation in invocations:
            self.assertIn("### :signal.branch\nmain\n", invocation["prompt"])
            self.assertIn("### :signal.type\nrepo-change\n", invocation["prompt"])

        for context_dir in (local_context_dir, core_context_dir, docs_context_dir):
            self.assertEqual((context_dir / ":signal.type").read_text(encoding="utf-8"), "repo-change")
            self.assertEqual((context_dir / ":signal.branch").read_text(encoding="utf-8"), "main")
            self.assertFalse((context_dir / ":signal.legacy").exists())
            self.assertEqual((context_dir / "shared").read_text(encoding="utf-8"), "keep-me")


if __name__ == "__main__":
    unittest.main()
