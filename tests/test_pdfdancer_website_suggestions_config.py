from __future__ import annotations

import unittest
from pathlib import Path

from propagate import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


class PdfdancerWebsiteSuggestionsConfigTests(unittest.TestCase):
    def test_config_loads_and_references_existing_prompt_files(self) -> None:
        config_path = REPO_ROOT / "config" / "pdfdancer-website-suggestions.yaml"
        create_prompt_path = REPO_ROOT / "config" / "prompts" / "pdfdancer" / "create-website-suggestions.md"
        validate_prompt_path = REPO_ROOT / "config" / "prompts" / "pdfdancer" / "validate-approved-website-suggestions.md"
        api_docs_prompt_path = REPO_ROOT / "config" / "prompts" / "pdfdancer" / "implement-approved-api-docs-suggestions.md"
        website_prompt_path = REPO_ROOT / "config" / "prompts" / "pdfdancer" / "implement-approved-website-suggestions.md"

        config = load_config(config_path)

        self.assertEqual(config.version, "6")
        self.assertEqual(tuple(config.repositories), ("pdfdancer-backend", "pdfdancer-api-docs", "pdfdancer-www"))
        self.assertIn("pull_request.labeled", config.signals)
        self.assertIn("issues.labeled", config.signals)
        self.assertEqual(tuple(config.executions), ("suggest-website-updates", "implement-approved-api-docs-updates", "implement-approved-website-updates"))
        self.assertEqual(len(config.propagation_triggers), 1)
        self.assertEqual(config.propagation_triggers[0].after, "implement-approved-api-docs-updates")
        self.assertEqual(config.propagation_triggers[0].run, "implement-approved-website-updates")

        suggest = config.executions["suggest-website-updates"]
        self.assertEqual(suggest.signals[0].signal_name, "pull_request.labeled")
        self.assertEqual(suggest.signals[0].when, {"repository": "MenschMachine/pdfdancer-backend", "label": "suggestions_needed"})

        api_docs = config.executions["implement-approved-api-docs-updates"]
        self.assertEqual(api_docs.signals[0].signal_name, "issues.labeled")
        self.assertEqual(api_docs.signals[0].when, {"repository": "MenschMachine/pdfdancer-www", "label": "approved"})
        self.assertIsNotNone(api_docs.git)
        self.assertEqual(api_docs.git.commit.message_key, ":api-docs-commit-message")
        self.assertEqual(api_docs.git.pr.body_key, ":api-docs-pr-body")
        self.assertEqual([task.task_id for task in api_docs.sub_tasks], ["validate-issue", "implement", "summarize", "publish", "wait-for-verdict", "validate-approved-pr"])
        self.assertEqual(
            api_docs.sub_tasks[1].before,
            [
                'propagate context set :api-docs-branch-name "api-docs/issue-$(propagate context get :signal.issue_number | xargs)"',
                "git:branch",
            ],
        )
        self.assertEqual(api_docs.sub_tasks[4].wait_for_signal, "pull_request.labeled")

        website = config.executions["implement-approved-website-updates"]
        self.assertEqual(website.signals, [])
        self.assertIsNotNone(website.git)
        self.assertEqual(website.git.commit.message_key, ":website-commit-message")
        self.assertEqual(website.git.pr.body_key, ":website-pr-body")
        self.assertEqual([task.task_id for task in website.sub_tasks], ["validate-issue", "implement", "summarize"])
        self.assertEqual(
            website.sub_tasks[1].before,
            [
                'propagate context set :website-branch-name "website/issue-$(propagate context get :signal.issue_number | xargs)"',
                "git:branch",
            ],
        )

        create_prompt = create_prompt_path.read_text(encoding="utf-8")
        self.assertIn("gh issue list --repo MenschMachine/pdfdancer-www --state open --limit 200 --json number,title,body,url", create_prompt)
        self.assertIn("<!-- propagate:pdfdancer-website-suggestions source-pr=MenschMachine/pdfdancer-backend#$PR_NUMBER -->", create_prompt)
        self.assertIn("website_suggestions", create_prompt)
        self.assertIn("## Recommended API Docs Changes", create_prompt)
        self.assertIn("## Recommended Website Changes", create_prompt)

        validate_prompt = validate_prompt_path.read_text(encoding="utf-8")
        self.assertIn("Website suggestions for backend PR #", validate_prompt)
        self.assertIn("website_suggestions", validate_prompt)

        api_docs_prompt = api_docs_prompt_path.read_text(encoding="utf-8")
        self.assertIn("## Recommended API Docs Changes", api_docs_prompt)

        website_prompt = website_prompt_path.read_text(encoding="utf-8")
        self.assertIn(":api-docs-pr-number --task implement-approved-api-docs-updates", website_prompt)
        self.assertIn("gh pr diff \"$API_DOCS_PR_NUMBER\" --repo MenschMachine/pdfdancer-api-docs", website_prompt)

        for execution in config.executions.values():
            for sub_task in execution.sub_tasks:
                if sub_task.prompt_path is not None:
                    self.assertTrue(sub_task.prompt_path.exists(), sub_task.prompt_path)
                    self.assertTrue(sub_task.prompt_path.is_file(), sub_task.prompt_path)


if __name__ == "__main__":
    unittest.main()
