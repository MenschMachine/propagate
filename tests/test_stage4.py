from __future__ import annotations

import json
import os
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


class PropagateStage4GitTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.workspace = Path(self.temp_dir.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.bin_dir = self.workspace / "bin"
        self.bin_dir.mkdir()
        self.remote_repo = self.workspace / "remote.git"
        self.mutate_repo_script = self.repo / "mutate_repo.py"
        self.emit_text_script = self.repo / "emit_text.py"
        self.fake_gh_script = self.bin_dir / "gh"
        self.gh_log = self.workspace / "gh-log.json"
        self.target_file = self.repo / "artifact.txt"
        self.prompt_path = self.repo / "config" / "prompts" / "task.md"
        self.config_path = self.repo / "config" / "propagate.yaml"

        self.mutate_repo_script.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "import sys",
                    "from pathlib import Path",
                    "",
                    "prompt_path = Path(sys.argv[1])",
                    "target_path = Path(sys.argv[2])",
                    "content = sys.argv[3]",
                    "if not prompt_path.exists():",
                    "    raise SystemExit('prompt file missing during agent run')",
                    "target_path.write_text(content, encoding='utf-8')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.emit_text_script.write_text(
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
        self.fake_gh_script.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "from __future__ import annotations",
                    "",
                    "import json",
                    "import os",
                    "import sys",
                    "from pathlib import Path",
                    "",
                    "args = sys.argv[1:]",
                    "fail_message = os.environ.get('PROPAGATE_GH_FAIL')",
                    "if fail_message:",
                    "    sys.stderr.write(fail_message)",
                    "    raise SystemExit(1)",
                    "body = ''",
                    "if '--body-file' in args:",
                    "    body_path = Path(args[args.index('--body-file') + 1])",
                    "    body = body_path.read_text(encoding='utf-8')",
                    "Path(os.environ['PROPAGATE_GH_LOG']).write_text(",
                    "    json.dumps({'args': args, 'body': body}),",
                    "    encoding='utf-8',",
                    ")",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.fake_gh_script.chmod(0o755)

    def run_cli(
        self,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        if env is not None:
            merged_env.update(env)
        return subprocess.run(
            [str(CLI_PYTHON), str(CLI_PATH), *args],
            cwd=cwd or self.repo,
            text=True,
            capture_output=True,
            check=False,
            env=merged_env,
        )

    def run_git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            text=True,
            capture_output=True,
            check=True,
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
                elif isinstance(item, list):
                    lines.append(f"{prefix}-")
                    lines.append(self.to_yaml(item, indent + 2).rstrip("\n"))
                else:
                    lines.append(f"{prefix}- {json.dumps(item)}")
            return "\n".join(lines) + "\n"
        return f"{prefix}{json.dumps(value)}\n"

    def init_repo(self) -> None:
        self.run_git("init", "-b", "main")
        self.run_git("config", "user.name", "Propagate Tests")
        self.run_git("config", "user.email", "propagate@example.com")

    def commit_all(self, message: str) -> None:
        self.run_git("add", "-A")
        self.run_git("commit", "-m", message)

    def write_config(
        self,
        git_config: dict[str, object],
        *,
        context_sources: dict[str, object] | None = None,
        agent_content: str = "updated from agent\n",
    ) -> None:
        self.prompt_path.parent.mkdir(parents=True, exist_ok=True)
        self.prompt_path.write_text("Task prompt.\n", encoding="utf-8")
        self.target_file.write_text("initial content\n", encoding="utf-8")

        command = self.build_python_command(
            self.mutate_repo_script,
            "{prompt_file}",
            str(self.target_file),
            agent_content,
        )
        config_data: dict[str, object] = {
            "version": "5",
            "agent": {"command": command},
            "executions": {
                "default": {
                    "git": git_config,
                    "sub_tasks": [
                        {
                            "id": "task",
                            "prompt": "./prompts/task.md",
                        }
                    ],
                }
            },
        }
        if context_sources is not None:
            config_data["context_sources"] = context_sources
        self.config_path.write_text(self.to_yaml(config_data), encoding="utf-8")

    def test_git_run_creates_branch_commit_push_and_pull_request(self) -> None:
        self.init_repo()
        self.run_git("init", "--bare", str(self.remote_repo), cwd=self.workspace)
        self.run_git("remote", "add", "origin", str(self.remote_repo))
        commit_message = "Stage 5 update\n\nPR body line"
        self.write_config(
            {
                "branch": {
                    "name": "propagate/build-stage5",
                    "base": "main",
                    "reuse": True,
                },
                "commit": {
                    "message_source": "commit-message",
                },
                "push": {
                    "remote": "origin",
                },
                "pr": {
                    "base": "main",
                    "draft": True,
                },
            },
            context_sources={
                "commit-message": {
                    "command": self.build_python_command(self.emit_text_script, commit_message),
                }
            },
        )
        self.commit_all("initial commit")

        result = self.run_cli(
            "run",
            "--config",
            str(self.config_path),
            env={
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "PROPAGATE_GH_LOG": str(self.gh_log),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.run_git("branch", "--show-current").stdout.strip(),
            "propagate/build-stage5",
        )
        self.assertEqual(
            self.run_git("log", "-1", "--pretty=%B").stdout.strip("\n"),
            commit_message,
        )
        self.assertEqual(
            (self.repo / ".propagate-context" / ":commit-message").read_text(encoding="utf-8"),
            commit_message,
        )
        self.run_git("rev-parse", "--verify", "refs/heads/propagate/build-stage5", cwd=self.remote_repo)

        gh_invocation = json.loads(self.gh_log.read_text(encoding="utf-8"))
        self.assertEqual(
            gh_invocation["args"][:8],
            [
                "pr",
                "create",
                "--base",
                "main",
                "--head",
                "propagate/build-stage5",
                "--title",
                "Stage 5 update",
            ],
        )
        self.assertEqual(gh_invocation["args"][-1], "--draft")
        self.assertEqual(gh_invocation["body"], "\nPR body line")

    def test_git_run_can_source_commit_message_from_reserved_context_key(self) -> None:
        self.init_repo()
        context_dir = self.repo / ".propagate-context"
        context_dir.mkdir()
        (context_dir / ":commit-message").write_text("Reserved key message\n\nBody line", encoding="utf-8")
        self.write_config(
            {
                "branch": {
                    "name": "propagate/key-commit",
                    "base": "main",
                    "reuse": True,
                },
                "commit": {
                    "message_key": ":commit-message",
                },
            }
        )
        self.commit_all("initial commit")

        result = self.run_cli("run", "--config", str(self.config_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.run_git("branch", "--show-current").stdout.strip(),
            "propagate/key-commit",
        )
        self.assertEqual(
            self.run_git("log", "-1", "--pretty=%B").stdout.strip("\n"),
            "Reserved key message\n\nBody line",
        )

    def test_git_run_fails_before_sub_tasks_when_working_tree_is_dirty(self) -> None:
        self.init_repo()
        self.write_config(
            {
                "branch": {
                    "name": "propagate/dirty-check",
                    "base": "main",
                    "reuse": True,
                },
                "commit": {
                    "message_source": "commit-message",
                },
            },
            context_sources={
                "commit-message": {
                    "command": self.build_python_command(self.emit_text_script, "Should not run"),
                }
            },
        )
        self.commit_all("initial commit")
        (self.repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")

        result = self.run_cli("run", "--config", str(self.config_path))

        self.assertEqual(result.returncode, 1)
        self.assertIn("clean working tree before execution", result.stderr)
        self.assertEqual(self.run_git("branch", "--show-current").stdout.strip(), "main")
        self.assertEqual(self.target_file.read_text(encoding="utf-8"), "initial content\n")
        self.assertEqual(int(self.run_git("rev-list", "--count", "HEAD").stdout.strip()), 1)

    def test_git_run_reports_execution_phase_and_stderr_when_pr_creation_fails(self) -> None:
        self.init_repo()
        self.run_git("init", "--bare", str(self.remote_repo), cwd=self.workspace)
        self.run_git("remote", "add", "origin", str(self.remote_repo))
        self.write_config(
            {
                "branch": {
                    "name": "propagate/pr-failure",
                    "base": "main",
                    "reuse": True,
                },
                "commit": {
                    "message_source": "commit-message",
                },
                "push": {
                    "remote": "origin",
                },
                "pr": {
                    "base": "main",
                    "draft": False,
                },
            },
            context_sources={
                "commit-message": {
                    "command": self.build_python_command(self.emit_text_script, "Subject line\n\nBody line"),
                }
            },
        )
        self.commit_all("initial commit")

        result = self.run_cli(
            "run",
            "--config",
            str(self.config_path),
            env={
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "PROPAGATE_GH_FAIL": "gh create failed loudly",
                "PROPAGATE_GH_LOG": str(self.gh_log),
            },
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Execution 'default' failed during PR creation", result.stderr)
        self.assertIn("gh create failed loudly", result.stderr)
        self.assertEqual(self.run_git("branch", "--show-current").stdout.strip(), "propagate/pr-failure")
        self.assertEqual(self.run_git("log", "-1", "--pretty=%B").stdout.strip("\n"), "Subject line\n\nBody line")
        self.run_git("rev-parse", "--verify", "refs/heads/propagate/pr-failure", cwd=self.remote_repo)


if __name__ == "__main__":
    unittest.main()
