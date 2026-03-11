from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from propagate import load_config


REPO_ROOT = Path(__file__).resolve().parents[1]


class Stage6ExampleBundleTests(unittest.TestCase):
    def test_stage6_example_bundle_loads_and_references_existing_files(self) -> None:
        bundle_dir = REPO_ROOT / "config" / "examples" / "stage6"
        config_path = bundle_dir / "propagate.yaml"
        readme_path = bundle_dir / "README.md"
        signal_path = bundle_dir / "signals" / "repo-change.yaml"

        self.assertTrue(readme_path.exists(), readme_path)
        self.assertTrue(signal_path.exists(), signal_path)

        config = load_config(config_path)

        self.assertEqual(config.version, "6")
        self.assertEqual(tuple(config.repositories), ("core-api", "docs-site"))
        self.assertEqual(tuple(config.signals), ("repo-change",))
        self.assertEqual(
            tuple(config.executions),
            (
                "triage-change",
                "prepare-core-context",
                "lint-docs",
                "update-docs",
                "review-docs",
                "archive-review",
                "publish-docs",
            ),
        )
        self.assertEqual(len(config.propagation_triggers), 2)

        for repository in config.repositories.values():
            self.assertTrue(repository.path.exists(), repository.path)
            self.assertTrue(repository.path.is_dir(), repository.path)

        for execution in config.executions.values():
            for sub_task in execution.sub_tasks:
                self.assertTrue(sub_task.prompt_path.exists(), sub_task.prompt_path)
                self.assertTrue(sub_task.prompt_path.is_file(), sub_task.prompt_path)

        archive_git = config.executions["archive-review"].git
        self.assertIsNotNone(archive_git)
        self.assertEqual(archive_git.commit.message_key, ":archive-commit-message")

        publish_git = config.executions["publish-docs"].git
        self.assertIsNotNone(publish_git)
        self.assertEqual(publish_git.commit.message_source, "docs-publish-commit")
        self.assertIsNotNone(publish_git.push)
        self.assertIsNotNone(publish_git.pr)

        signal_document = yaml.safe_load(signal_path.read_text(encoding="utf-8"))
        self.assertEqual(signal_document["type"], "repo-change")
        self.assertEqual(signal_document["payload"]["branch"], "main")
        self.assertEqual(signal_document["payload"]["release"], 6)


if __name__ == "__main__":
    unittest.main()
