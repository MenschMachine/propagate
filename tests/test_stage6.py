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

from propagate_app.run_state import state_file_path

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
        (self.config_dir / ".propagate-context" / "build-core").mkdir(parents=True)
        (self.config_dir / ".propagate-context" / "prepare-docs-context").mkdir(parents=True)
        (self.config_dir / ".propagate-context" / "build-core" / ":signal.type").write_text("stale-core", encoding="utf-8")
        (self.config_dir / ".propagate-context" / "prepare-docs-context" / ":signal.type").write_text("stale-docs", encoding="utf-8")

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
            (self.config_dir / ".propagate-context" / "build-core" / ":signal.type").read_text(encoding="utf-8"),
            "repo-change",
        )
        self.assertEqual(
            (self.config_dir / ".propagate-context" / "prepare-docs-context" / ":signal.type").read_text(encoding="utf-8"),
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

        local_context_dir = self.config_dir / ".propagate-context" / "start-local"
        core_context_dir = self.config_dir / ".propagate-context" / "build-core"
        docs_context_dir = self.config_dir / ".propagate-context" / "update-docs"
        local_context_dir.mkdir(parents=True)
        core_context_dir.mkdir(parents=True)
        docs_context_dir.mkdir(parents=True)

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
            self.assertFalse((context_dir / "shared").exists(), "Pre-existing context should be cleared on fresh run")


    def _create_bare_repo(self, name: str, branch: str = "main") -> Path:
        bare_dir = self.workspace / name
        bare_dir.mkdir()
        subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True, capture_output=True)
        work_dir = self.workspace / f"{name}-work"
        work_dir.mkdir()
        subprocess.run(["git", "clone", str(bare_dir), str(work_dir)], check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", branch], cwd=str(work_dir), check=True, capture_output=True)
        dummy = work_dir / "README.md"
        dummy.write_text("init\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(work_dir), check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@test", "commit", "-m", "init"],
            cwd=str(work_dir), check=True, capture_output=True,
        )
        subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(work_dir), check=True, capture_output=True)
        shutil.rmtree(work_dir)
        return bare_dir

    def test_url_repository_is_cloned_into_temp_dir_and_execution_runs_there(self) -> None:
        bare_repo = self._create_bare_repo("remote-repo")
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
                    "remote": {"url": str(bare_repo)},
                },
                "executions": {
                    "task": {
                        "repository": "remote",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "task", cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        self.assertEqual(len(invocations), 1)
        cwd_path = Path(invocations[0]["cwd"])
        self.addCleanup(shutil.rmtree, cwd_path, True)
        self.assertNotEqual(cwd_path.resolve(), bare_repo.resolve())
        self.assertIn("README.md", invocations[0]["files"])

    def test_url_repository_with_ref_checks_out_specified_branch(self) -> None:
        bare_repo = self._create_bare_repo("ref-repo")
        work_dir = self.workspace / "ref-repo-work2"
        work_dir.mkdir()
        subprocess.run(["git", "clone", str(bare_repo), str(work_dir)], check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=str(work_dir), check=True, capture_output=True)
        (work_dir / "feature.txt").write_text("feature\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(work_dir), check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@test", "commit", "-m", "feature"],
            cwd=str(work_dir), check=True, capture_output=True,
        )
        subprocess.run(["git", "push", "-u", "origin", "feature"], cwd=str(work_dir), check=True, capture_output=True)
        shutil.rmtree(work_dir)

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
                    "remote": {"url": str(bare_repo), "ref": "feature"},
                },
                "executions": {
                    "task": {
                        "repository": "remote",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "task", cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        cwd_path = Path(invocations[0]["cwd"])
        self.addCleanup(shutil.rmtree, cwd_path, True)
        self.assertIn("feature.txt", invocations[0]["files"])

    def test_url_repository_clone_failure_reports_clear_error(self) -> None:
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
                    "remote": {"url": "/nonexistent/repo/path"},
                },
                "executions": {
                    "task": {
                        "repository": "remote",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "task", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Failed to clone repository 'remote'", result.stderr)

    def test_url_repository_temp_dir_persists_after_execution(self) -> None:
        bare_repo = self._create_bare_repo("persist-repo")
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
                    "remote": {"url": str(bare_repo)},
                },
                "executions": {
                    "task": {
                        "repository": "remote",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "task", cwd=self.workspace)

        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        cwd_path = Path(invocations[0]["cwd"])
        self.assertTrue(cwd_path.exists(), f"Cloned repo should persist after execution: {cwd_path}")
        self.addCleanup(shutil.rmtree, cwd_path, True)

    def test_url_repository_with_nonexistent_ref_fails_with_clear_error(self) -> None:
        bare_repo = self._create_bare_repo("bad-ref-repo")
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
                    "remote": {"url": str(bare_repo), "ref": "nonexistent-branch"},
                },
                "executions": {
                    "task": {
                        "repository": "remote",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "task", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Failed to checkout ref 'nonexistent-branch' for repository 'remote'", result.stderr)

    def test_repository_with_ref_but_path_fails_during_config_load(self) -> None:
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
                    "local": {"path": "../some-dir", "ref": "main"},
                },
                "executions": {
                    "task": {
                        "repository": "local",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "task", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("declares 'ref' without 'url'", result.stderr)

    def test_repository_with_both_path_and_url_fails_during_config_load(self) -> None:
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
                    "both": {"path": "../some-dir", "url": "https://github.com/org/repo"},
                },
                "executions": {
                    "task": {
                        "repository": "both",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    }
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "task", cwd=self.workspace)

        self.assertEqual(result.returncode, 1)
        self.assertIn("must declare either 'path' or 'url', not both", result.stderr)


class PropagateResumeTests(unittest.TestCase):
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

    def _create_bare_repo(self, name: str, branch: str = "main") -> Path:
        bare_dir = self.workspace / name
        bare_dir.mkdir()
        subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True, capture_output=True)
        work_dir = self.workspace / f"{name}-work"
        work_dir.mkdir()
        subprocess.run(["git", "clone", str(bare_dir), str(work_dir)], check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", branch], cwd=str(work_dir), check=True, capture_output=True)
        dummy = work_dir / "README.md"
        dummy.write_text("init\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(work_dir), check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@test", "commit", "-m", "init"],
            cwd=str(work_dir), check=True, capture_output=True,
        )
        subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(work_dir), check=True, capture_output=True)
        shutil.rmtree(work_dir)
        return bare_dir

    def test_resume_skips_completed_executions(self) -> None:
        repo_dir = self.workspace / "repo"
        repo_dir.mkdir()
        (self.prompt_dir / "step-a.md").write_text("step-a\n", encoding="utf-8")
        (self.prompt_dir / "step-b.md").write_text("step-b\n", encoding="utf-8")
        (self.prompt_dir / "step-c.md").write_text("step-c\n", encoding="utf-8")

        fail_on_file = self.workspace / "fail_on.txt"
        fail_on_file.write_text("step-b", encoding="utf-8")

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
                    "step-a": {
                        "repository": "repo",
                        "sub_tasks": [{"id": "a", "prompt": "./prompts/step-a.md"}],
                    },
                    "step-b": {
                        "repository": "repo",
                        "depends_on": ["step-a"],
                        "sub_tasks": [{"id": "b", "prompt": "./prompts/step-b.md"}],
                    },
                    "step-c": {
                        "repository": "repo",
                        "depends_on": ["step-b"],
                        "sub_tasks": [{"id": "c", "prompt": "./prompts/step-c.md"}],
                    },
                },
            }
        )

        # First run: step-a succeeds, step-b fails
        result = self.run_cli("run", "--config", str(config_path), "--execution", "step-c")
        self.assertEqual(result.returncode, 1)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        self.assertEqual(len(invocations), 2)  # step-a and step-b attempted

        # State file should exist
        state_file = state_file_path(config_path)
        self.assertTrue(state_file.exists(), "State file should be saved after step-a completes")

        # Now fix the failure and resume
        fail_on_file.write_text("never", encoding="utf-8")
        self.invocation_log.unlink()

        result = self.run_cli("run", "--config", str(config_path), "--resume")
        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        # Only step-b and step-c should run (step-a was completed)
        prompts = [inv["prompt"].strip() for inv in invocations]
        self.assertEqual(prompts, ["step-b", "step-c"])
        self.assertIn("Resuming execution schedule", result.stderr)

    def test_resume_reuses_cloned_url_repository(self) -> None:
        bare_repo = self._create_bare_repo("resume-remote")
        (self.prompt_dir / "task-first.md").write_text("task-first\n", encoding="utf-8")
        (self.prompt_dir / "task-second.md").write_text("task-second\n", encoding="utf-8")

        fail_on_file = self.workspace / "fail_on.txt"
        fail_on_file.write_text("task-second", encoding="utf-8")

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
                    "remote": {"url": str(bare_repo)},
                },
                "executions": {
                    "task-first": {
                        "repository": "remote",
                        "sub_tasks": [{"id": "first", "prompt": "./prompts/task-first.md"}],
                    },
                    "task-second": {
                        "repository": "remote",
                        "depends_on": ["task-first"],
                        "sub_tasks": [{"id": "second", "prompt": "./prompts/task-second.md"}],
                    },
                },
            }
        )

        # First run: task-first succeeds, task-second fails
        result = self.run_cli("run", "--config", str(config_path), "--execution", "task-second")
        self.assertEqual(result.returncode, 1)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        first_clone_dir = Path(invocations[0]["cwd"])
        self.addCleanup(shutil.rmtree, first_clone_dir, True)

        # Verify state file saved clone path
        state_file = state_file_path(config_path)
        self.assertTrue(state_file.exists())

        state_data = yaml.safe_load(state_file.read_text(encoding="utf-8"))
        self.assertEqual(
            Path(state_data["cloned_repos"]["remote"]).resolve(),
            first_clone_dir.resolve(),
        )

        # Resume - should reuse clone, not create new one
        fail_on_file.write_text("never", encoding="utf-8")
        self.invocation_log.unlink()

        result = self.run_cli("run", "--config", str(config_path), "--resume")
        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        # Should run in same clone dir
        for inv in invocations:
            self.assertEqual(Path(inv["cwd"]).resolve(), first_clone_dir.resolve())
        self.assertIn("Reusing existing clone", result.stderr)

    def test_successful_run_clears_state_file(self) -> None:
        repo_dir = self.workspace / "repo"
        repo_dir.mkdir()
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
                    "repo": {"path": "../repo"},
                },
                "executions": {
                    "task": {
                        "repository": "repo",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    },
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--execution", "task")
        self.assertEqual(result.returncode, 0, result.stderr)

        state_file = state_file_path(config_path)
        self.assertFalse(state_file.exists(), "State file should be deleted after successful completion")

    def test_resume_without_state_file_fails(self) -> None:
        repo_dir = self.workspace / "repo"
        repo_dir.mkdir()
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
                    "repo": {"path": "../repo"},
                },
                "executions": {
                    "task": {
                        "repository": "repo",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    },
                },
            }
        )

        result = self.run_cli("run", "--config", str(config_path), "--resume")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No run state file found", result.stderr)
        self.assertIn("Nothing to resume", result.stderr)

    def test_resume_with_missing_clone_dir_fails(self) -> None:
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
                    "remote": {"url": "/some/repo"},
                },
                "executions": {
                    "task": {
                        "repository": "remote",
                        "sub_tasks": [{"id": "task", "prompt": "./prompts/task.md"}],
                    },
                },
            }
        )

        # Manually write a state file with a nonexistent clone dir

        state_file = state_file_path(config_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_data = {
            "config_path": str(config_path.resolve()),
            "initial_execution": "task",
            "active_names": ["task"],
            "completed_names": [],
            "cloned_repos": {"remote": "/tmp/nonexistent-propagate-clone-xyz"},
            "initialized_signal_context_dirs": [],
        }
        state_file.write_text(yaml.dump(state_data), encoding="utf-8")

        result = self.run_cli("run", "--config", str(config_path), "--resume")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no longer exists", result.stderr)


    def test_resume_retries_failed_first_execution(self) -> None:
        repo_dir = self.workspace / "repo"
        repo_dir.mkdir()
        (self.prompt_dir / "only-step.md").write_text("only-step\n", encoding="utf-8")

        fail_on_file = self.workspace / "fail_on.txt"
        fail_on_file.write_text("only-step", encoding="utf-8")

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
                    "only-step": {
                        "repository": "repo",
                        "sub_tasks": [{"id": "a", "prompt": "./prompts/only-step.md"}],
                    },
                },
            }
        )

        # First run: only-step fails immediately
        result = self.run_cli("run", "--config", str(config_path), "--execution", "only-step")
        self.assertEqual(result.returncode, 1)

        # State file should exist (saved before execution started)
        state_file = state_file_path(config_path)
        self.assertTrue(state_file.exists(), "State file should exist even when first execution fails")

        # Fix the failure and resume
        fail_on_file.write_text("never", encoding="utf-8")
        self.invocation_log.unlink()

        result = self.run_cli("run", "--config", str(config_path), "--resume")
        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        prompts = [inv["prompt"].strip() for inv in invocations]
        self.assertEqual(prompts, ["only-step"])

        # State file should be cleared after success
        self.assertFalse(state_file.exists())


if __name__ == "__main__":
    unittest.main()
