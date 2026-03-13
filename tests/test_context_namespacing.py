from __future__ import annotations

import json
import os
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


class ContextStoreUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def test_get_context_root_returns_sibling_of_config(self) -> None:
        from propagate_app.context_store import get_context_root

        config_path = self.root / "project" / "propagate.yaml"
        result = get_context_root(config_path)
        self.assertEqual(result, self.root / "project" / ".propagate-context")

    def test_get_global_context_dir_returns_root(self) -> None:
        from propagate_app.context_store import get_global_context_dir

        context_root = self.root / ".propagate-context"
        self.assertEqual(get_global_context_dir(context_root), context_root)

    def test_get_execution_context_dir(self) -> None:
        from propagate_app.context_store import get_execution_context_dir

        context_root = self.root / ".propagate-context"
        self.assertEqual(
            get_execution_context_dir(context_root, "build"),
            context_root / "build",
        )

    def test_get_task_context_dir(self) -> None:
        from propagate_app.context_store import get_task_context_dir

        context_root = self.root / ".propagate-context"
        self.assertEqual(
            get_task_context_dir(context_root, "build", "review"),
            context_root / "build" / "review",
        )

    def test_resolve_context_dir_for_write_default_scope(self) -> None:
        from propagate_app.context_store import resolve_context_dir_for_write

        context_root = self.root / ".propagate-context"
        result = resolve_context_dir_for_write(context_root, "build", "task1")
        self.assertEqual(result, context_root / "build")

    def test_resolve_context_dir_for_write_global_scope(self) -> None:
        from propagate_app.context_store import resolve_context_dir_for_write

        context_root = self.root / ".propagate-context"
        result = resolve_context_dir_for_write(context_root, "build", "task1", scope_global=True)
        self.assertEqual(result, context_root)

    def test_resolve_context_dir_for_write_local_scope(self) -> None:
        from propagate_app.context_store import resolve_context_dir_for_write

        context_root = self.root / ".propagate-context"
        result = resolve_context_dir_for_write(context_root, "build", "task1", scope_local=True)
        self.assertEqual(result, context_root / "build" / "task1")

    def test_resolve_context_dir_for_write_local_scope_requires_task(self) -> None:
        from propagate_app.context_store import resolve_context_dir_for_write
        from propagate_app.errors import PropagateError

        context_root = self.root / ".propagate-context"
        with self.assertRaises(PropagateError) as cm:
            resolve_context_dir_for_write(context_root, "build", "", scope_local=True)
        self.assertIn("--local requires a task context", str(cm.exception))

    def test_resolve_context_dir_for_read_task_scope_single_part(self) -> None:
        from propagate_app.context_store import resolve_context_dir_for_read

        context_root = self.root / ".propagate-context"
        result = resolve_context_dir_for_read(context_root, "build", "", scope_task="sdk-python")
        self.assertEqual(result, context_root / "sdk-python")

    def test_resolve_context_dir_for_read_task_scope_two_parts(self) -> None:
        from propagate_app.context_store import resolve_context_dir_for_read

        context_root = self.root / ".propagate-context"
        result = resolve_context_dir_for_read(context_root, "build", "", scope_task="sdk-python/review")
        self.assertEqual(result, context_root / "sdk-python" / "review")

    def test_resolve_context_dir_for_read_task_scope_rejects_multiple_slashes(self) -> None:
        from propagate_app.context_store import resolve_context_dir_for_read
        from propagate_app.errors import PropagateError

        context_root = self.root / ".propagate-context"
        with self.assertRaises(PropagateError):
            resolve_context_dir_for_read(context_root, "build", "", scope_task="a/b/c")

    def test_resolve_context_dir_for_read_task_scope_rejects_empty_parts(self) -> None:
        from propagate_app.context_store import resolve_context_dir_for_read
        from propagate_app.errors import PropagateError

        context_root = self.root / ".propagate-context"
        with self.assertRaises(PropagateError):
            resolve_context_dir_for_read(context_root, "build", "", scope_task="a/")

    def test_resolve_context_dir_for_read_local_requires_task(self) -> None:
        from propagate_app.context_store import resolve_context_dir_for_read
        from propagate_app.errors import PropagateError

        context_root = self.root / ".propagate-context"
        with self.assertRaises(PropagateError) as cm:
            resolve_context_dir_for_read(context_root, "build", "", scope_local=True)
        self.assertIn("--local requires a task context", str(cm.exception))

    def test_merge_context_layers_deeper_wins(self) -> None:
        from propagate_app.context_store import merge_context_layers

        global_items = [("a", "global-a"), ("b", "global-b")]
        execution_items = [("b", "exec-b"), ("c", "exec-c")]
        task_items = [("c", "task-c")]
        result = merge_context_layers(global_items, execution_items, task_items)
        self.assertEqual(
            result,
            [("a", "global-a"), ("b", "exec-b"), ("c", "task-c")],
        )

    def test_load_merged_context_combines_three_layers(self) -> None:
        from propagate_app.context_store import (
            ensure_context_dir,
            load_merged_context,
            write_context_value,
        )

        context_root = self.root / ".propagate-context"
        global_dir = context_root
        exec_dir = context_root / "build"
        task_dir = context_root / "build" / "review"
        ensure_context_dir(global_dir)
        ensure_context_dir(exec_dir)
        ensure_context_dir(task_dir)
        write_context_value(global_dir, "shared", "global-value")
        write_context_value(global_dir, "global-only", "g")
        write_context_value(exec_dir, "shared", "exec-value")
        write_context_value(exec_dir, "exec-only", "e")
        write_context_value(task_dir, "shared", "task-value")
        write_context_value(task_dir, "task-only", "t")

        result = load_merged_context(context_root, "build", "review")
        result_dict = dict(result)
        self.assertEqual(result_dict["shared"], "task-value")
        self.assertEqual(result_dict["global-only"], "g")
        self.assertEqual(result_dict["exec-only"], "e")
        self.assertEqual(result_dict["task-only"], "t")

    def test_load_local_context_skips_subdirectories(self) -> None:
        from propagate_app.context_store import (
            ensure_context_dir,
            load_local_context,
            write_context_value,
        )

        context_root = self.root / ".propagate-context"
        ensure_context_dir(context_root)
        write_context_value(context_root, "key1", "value1")
        (context_root / "subdir").mkdir()
        (context_root / "subdir" / "nested").write_text("nested", encoding="utf-8")

        result = load_local_context(context_root)
        self.assertEqual(result, [("key1", "value1")])

    def test_resolve_execution_context_dir_from_runtime_context(self) -> None:
        from propagate_app.context_store import resolve_execution_context_dir
        from propagate_app.models import RuntimeContext

        context_root = self.root / ".propagate-context"
        rc = RuntimeContext(
            agent_command="test",
            context_sources={},
            active_signal=None,
            initialized_signal_context_dirs=set(),
            working_dir=self.root,
            context_root=context_root,
            execution_name="build",
        )
        result = resolve_execution_context_dir(rc)
        self.assertEqual(result, context_root / "build")

    def test_build_context_env_empty_task(self) -> None:
        from propagate_app.models import RuntimeContext
        from propagate_app.sub_tasks import build_context_env

        context_root = self.root / ".propagate-context"
        rc = RuntimeContext(
            agent_command="test",
            context_sources={},
            active_signal=None,
            initialized_signal_context_dirs=set(),
            working_dir=self.root,
            context_root=context_root,
            execution_name="build",
            task_id="",
        )
        env = build_context_env(rc)
        self.assertEqual(env["PROPAGATE_TASK"], "")
        self.assertEqual(env["PROPAGATE_EXECUTION"], "build")
        self.assertEqual(env["PROPAGATE_CONTEXT_ROOT"], str(context_root))


class ContextCLIScopeTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.workspace = Path(self.temp_dir.name)

    def run_cli(self, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI_PYTHON), str(CLI_PATH), *args],
            cwd=cwd or self.workspace,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def test_set_with_task_flag_is_rejected_by_argparse(self) -> None:
        result = self.run_cli("context", "set", "key", "value", "--task", "some/task", cwd=self.workspace)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_global_local_task_flags_are_mutually_exclusive(self) -> None:
        result = self.run_cli("context", "set", "key", "value", "--global", "--local", cwd=self.workspace)
        self.assertNotEqual(result.returncode, 0)

    def test_set_global_writes_to_context_root(self) -> None:
        context_root = self.workspace / ".propagate-context"
        env = {
            **os.environ,
            "PROPAGATE_CONTEXT_ROOT": str(context_root),
            "PROPAGATE_EXECUTION": "build",
            "PROPAGATE_TASK": "",
        }
        result = self.run_cli("context", "set", "release", "1.0", "--global", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (context_root / "release").read_text(encoding="utf-8"),
            "1.0",
        )

    def test_set_default_writes_to_execution_dir(self) -> None:
        context_root = self.workspace / ".propagate-context"
        env = {
            **os.environ,
            "PROPAGATE_CONTEXT_ROOT": str(context_root),
            "PROPAGATE_EXECUTION": "build",
            "PROPAGATE_TASK": "",
        }
        result = self.run_cli("context", "set", "status", "running", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (context_root / "build" / "status").read_text(encoding="utf-8"),
            "running",
        )

    def test_set_local_writes_to_task_dir(self) -> None:
        context_root = self.workspace / ".propagate-context"
        env = {
            **os.environ,
            "PROPAGATE_CONTEXT_ROOT": str(context_root),
            "PROPAGATE_EXECUTION": "build",
            "PROPAGATE_TASK": "review",
        }
        result = self.run_cli("context", "set", "note", "task-level", "--local", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (context_root / "build" / "review" / "note").read_text(encoding="utf-8"),
            "task-level",
        )

    def test_get_task_reads_from_other_execution(self) -> None:
        context_root = self.workspace / ".propagate-context"
        target_dir = context_root / "sdk-python"
        target_dir.mkdir(parents=True)
        (target_dir / "version").write_text("2.0", encoding="utf-8")

        env = {
            **os.environ,
            "PROPAGATE_CONTEXT_ROOT": str(context_root),
            "PROPAGATE_EXECUTION": "build",
            "PROPAGATE_TASK": "",
        }
        result = self.run_cli("context", "get", "version", "--task", "sdk-python", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "2.0")

    def test_get_task_reads_from_execution_slash_task(self) -> None:
        context_root = self.workspace / ".propagate-context"
        target_dir = context_root / "sdk-python" / "review"
        target_dir.mkdir(parents=True)
        (target_dir / "findings").write_text("all good", encoding="utf-8")

        env = {
            **os.environ,
            "PROPAGATE_CONTEXT_ROOT": str(context_root),
            "PROPAGATE_EXECUTION": "build",
            "PROPAGATE_TASK": "",
        }
        result = self.run_cli("context", "get", "findings", "--task", "sdk-python/review", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "all good")

    def test_get_local_without_env_vars_errors_because_no_task(self) -> None:
        result = self.run_cli("context", "get", "key", "--local", cwd=self.workspace)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--local requires a task context", result.stderr)

    def test_get_task_multiple_slashes_rejected(self) -> None:
        context_root = self.workspace / ".propagate-context"
        env = {
            **os.environ,
            "PROPAGATE_CONTEXT_ROOT": str(context_root),
            "PROPAGATE_EXECUTION": "build",
            "PROPAGATE_TASK": "",
        }
        result = self.run_cli("context", "get", "key", "--task", "a/b/c", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--task", result.stderr)

    def test_fallback_without_env_vars_uses_cwd(self) -> None:
        result = self.run_cli("context", "set", "key", "value", cwd=self.workspace)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.workspace / ".propagate-context" / "key").read_text(encoding="utf-8"),
            "value",
        )

    def test_set_global_without_env_vars_writes_to_cwd_context_root(self) -> None:
        result = self.run_cli("context", "set", "release", "1.0", "--global", cwd=self.workspace)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.workspace / ".propagate-context" / "release").read_text(encoding="utf-8"),
            "1.0",
        )

    def test_set_local_without_env_vars_errors_because_no_task(self) -> None:
        result = self.run_cli("context", "set", "key", "value", "--local", cwd=self.workspace)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--local requires a task context", result.stderr)

    def test_get_global_without_env_vars_reads_from_cwd_context_root(self) -> None:
        context_root = self.workspace / ".propagate-context"
        context_root.mkdir()
        (context_root / "release").write_text("1.0", encoding="utf-8")
        result = self.run_cli("context", "get", "release", "--global", cwd=self.workspace)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "1.0")

    def test_dump_shows_all_scopes(self) -> None:
        context_root = self.workspace / ".propagate-context"
        exec_dir = context_root / "build"
        exec_dir.mkdir(parents=True)
        (context_root / "global-key").write_text("global-value", encoding="utf-8")
        (exec_dir / "exec-key").write_text("exec-value", encoding="utf-8")

        env = {
            **os.environ,
            "PROPAGATE_CONTEXT_ROOT": str(context_root),
            "PROPAGATE_EXECUTION": "build",
            "PROPAGATE_TASK": "",
        }
        result = self.run_cli("context", "dump", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = yaml.safe_load(result.stdout)
        self.assertEqual(parsed, {
            "global": {"global-key": "global-value"},
            "executions": {
                "build": {
                    "context": {"exec-key": "exec-value"},
                    "tasks": {},
                },
            },
        })

    def test_dump_empty_context_outputs_empty_yaml(self) -> None:
        context_root = self.workspace / ".propagate-context"
        context_root.mkdir(parents=True)

        env = {
            **os.environ,
            "PROPAGATE_CONTEXT_ROOT": str(context_root),
            "PROPAGATE_EXECUTION": "build",
            "PROPAGATE_TASK": "",
        }
        result = self.run_cli("context", "dump", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = yaml.safe_load(result.stdout)
        self.assertEqual(parsed, {"global": {}, "executions": {}})

    def test_dump_without_env_vars_uses_cwd(self) -> None:
        context_root = self.workspace / ".propagate-context"
        context_root.mkdir(parents=True)
        (context_root / "whoami").write_text("michael", encoding="utf-8")

        result = self.run_cli("context", "dump", cwd=self.workspace)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = yaml.safe_load(result.stdout)
        self.assertEqual(parsed, {"global": {"whoami": "michael"}, "executions": {}})

    def test_dump_shows_all_executions_and_tasks(self) -> None:
        context_root = self.workspace / ".propagate-context"
        exec_a = context_root / "build"
        exec_b = context_root / "deploy"
        task_dir = exec_a / "review"
        task_dir.mkdir(parents=True)
        exec_b.mkdir(parents=True)
        (context_root / "shared").write_text("global", encoding="utf-8")
        (exec_a / "status").write_text("done", encoding="utf-8")
        (task_dir / "findings").write_text("ok", encoding="utf-8")
        (exec_b / "target").write_text("prod", encoding="utf-8")

        env = {
            **os.environ,
            "PROPAGATE_CONTEXT_ROOT": str(context_root),
            "PROPAGATE_EXECUTION": "build",
            "PROPAGATE_TASK": "review",
        }
        result = self.run_cli("context", "dump", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = yaml.safe_load(result.stdout)
        self.assertEqual(parsed, {
            "global": {"shared": "global"},
            "executions": {
                "build": {
                    "context": {"status": "done"},
                    "tasks": {
                        "review": {"findings": "ok"},
                    },
                },
                "deploy": {
                    "context": {"target": "prod"},
                    "tasks": {},
                },
            },
        })

    def test_get_task_without_env_vars_reads_from_task_path(self) -> None:
        context_root = self.workspace / ".propagate-context"
        target_dir = context_root / "sdk-python" / "review"
        target_dir.mkdir(parents=True)
        (target_dir / "findings").write_text("all good", encoding="utf-8")
        result = self.run_cli("context", "get", "findings", "--task", "sdk-python/review", cwd=self.workspace)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "all good")


class ContextEnvVarsIntegrationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.workspace = Path(self.temp_dir.name)
        self.config_dir = self.workspace / "config"
        self.prompt_dir = self.config_dir / "prompts"
        self.prompt_dir.mkdir(parents=True)
        self.invocation_log = self.workspace / "invocations.json"
        self.env_capture_script = self.workspace / "capture_env.py"
        self.env_capture_script.write_text(
            "\n".join([
                "from __future__ import annotations",
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
                "    'PROPAGATE_CONTEXT_ROOT': os.environ.get('PROPAGATE_CONTEXT_ROOT', ''),",
                "    'PROPAGATE_EXECUTION': os.environ.get('PROPAGATE_EXECUTION', ''),",
                "    'PROPAGATE_TASK': os.environ.get('PROPAGATE_TASK', ''),",
                "    'prompt': prompt_path.read_text(encoding='utf-8'),",
                "})",
                "log_path.write_text(json.dumps(items), encoding='utf-8')",
            ]) + "\n",
            encoding="utf-8",
        )

    def build_python_command(self, script_path: Path, *args: str) -> str:
        parts = [shlex.quote(str(CLI_PYTHON)), shlex.quote(str(script_path))]
        parts.extend(shlex.quote(arg) for arg in args)
        return " ".join(parts)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI_PYTHON), str(CLI_PATH), *args],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_agent_receives_context_env_vars(self) -> None:
        (self.prompt_dir / "task.md").write_text("task prompt\n", encoding="utf-8")
        config_path = self.config_dir / "propagate.yaml"
        repositories, patched = inject_test_repository(
            {
                "deploy": {
                    "sub_tasks": [{"id": "plan", "prompt": "./prompts/task.md"}],
                }
            },
            self.workspace,
        )
        config_path.write_text(
            yaml.dump(
                {
                    "version": "6",
                    "agent": {
                        "command": self.build_python_command(
                            self.env_capture_script,
                            "{prompt_file}",
                            str(self.invocation_log),
                        )
                    },
                    "repositories": repositories,
                    "executions": patched,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = self.run_cli("run", "--config", str(config_path))
        self.assertEqual(result.returncode, 0, result.stderr)

        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        self.assertEqual(len(invocations), 1)
        env_data = invocations[0]
        self.assertEqual(
            Path(env_data["PROPAGATE_CONTEXT_ROOT"]).resolve(),
            (self.config_dir / ".propagate-context").resolve(),
        )
        self.assertEqual(env_data["PROPAGATE_EXECUTION"], "deploy")
        self.assertEqual(env_data["PROPAGATE_TASK"], "plan")

    def test_merged_context_in_prompt_global_plus_execution(self) -> None:
        (self.prompt_dir / "task.md").write_text("task prompt\n", encoding="utf-8")
        context_root = self.config_dir / ".propagate-context"
        global_dir = context_root
        exec_dir = context_root / "deploy"
        global_dir.mkdir(parents=True)
        exec_dir.mkdir(parents=True)
        (global_dir / "release").write_text("1.0", encoding="utf-8")
        (exec_dir / "release").write_text("2.0", encoding="utf-8")
        (exec_dir / "env").write_text("prod", encoding="utf-8")

        config_path = self.config_dir / "propagate.yaml"
        repositories, patched = inject_test_repository(
            {
                "deploy": {
                    "sub_tasks": [{"id": "plan", "prompt": "./prompts/task.md"}],
                }
            },
            self.workspace,
        )
        config_path.write_text(
            yaml.dump(
                {
                    "version": "6",
                    "agent": {
                        "command": self.build_python_command(
                            self.env_capture_script,
                            "{prompt_file}",
                            str(self.invocation_log),
                        )
                    },
                    "repositories": repositories,
                    "executions": patched,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = self.run_cli("run", "--config", str(config_path))
        self.assertEqual(result.returncode, 0, result.stderr)

        invocations = json.loads(self.invocation_log.read_text(encoding="utf-8"))
        prompt = invocations[0]["prompt"]
        self.assertIn("### env\nprod\n", prompt)
        self.assertIn("### release\n2.0\n", prompt)
        self.assertNotIn("1.0", prompt)

    def test_hook_receives_context_env_vars(self) -> None:
        (self.prompt_dir / "task.md").write_text("task\n", encoding="utf-8")
        hook_log = self.workspace / "hook-env.json"
        hook_script = self.workspace / "hook_capture_env.py"
        hook_script.write_text(
            "\n".join([
                "from __future__ import annotations",
                "import json",
                "import os",
                "import sys",
                "from pathlib import Path",
                "",
                "log_path = Path(sys.argv[1])",
                "items = []",
                "if log_path.exists():",
                "    items = json.loads(log_path.read_text(encoding='utf-8'))",
                "items.append({",
                "    'PROPAGATE_CONTEXT_ROOT': os.environ.get('PROPAGATE_CONTEXT_ROOT', ''),",
                "    'PROPAGATE_EXECUTION': os.environ.get('PROPAGATE_EXECUTION', ''),",
                "    'PROPAGATE_TASK': os.environ.get('PROPAGATE_TASK', ''),",
                "})",
                "log_path.write_text(json.dumps(items), encoding='utf-8')",
            ]) + "\n",
            encoding="utf-8",
        )

        config_path = self.config_dir / "propagate.yaml"
        repositories, patched = inject_test_repository(
            {
                "deploy": {
                    "sub_tasks": [
                        {
                            "id": "plan",
                            "prompt": "./prompts/task.md",
                            "before": [
                                self.build_python_command(hook_script, str(hook_log)),
                            ],
                        }
                    ],
                }
            },
            self.workspace,
        )
        config_path.write_text(
            yaml.dump(
                {
                    "version": "6",
                    "agent": {
                        "command": self.build_python_command(
                            self.env_capture_script,
                            "{prompt_file}",
                            str(self.invocation_log),
                        )
                    },
                    "repositories": repositories,
                    "executions": patched,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = self.run_cli("run", "--config", str(config_path))
        self.assertEqual(result.returncode, 0, result.stderr)

        hook_data = json.loads(hook_log.read_text(encoding="utf-8"))
        self.assertEqual(len(hook_data), 1)
        self.assertEqual(
            Path(hook_data[0]["PROPAGATE_CONTEXT_ROOT"]).resolve(),
            (self.config_dir / ".propagate-context").resolve(),
        )
        self.assertEqual(hook_data[0]["PROPAGATE_EXECUTION"], "deploy")
        self.assertEqual(hook_data[0]["PROPAGATE_TASK"], "plan")


if __name__ == "__main__":
    unittest.main()
