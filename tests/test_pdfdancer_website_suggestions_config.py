from __future__ import annotations

import unittest
from pathlib import Path

from propagate import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


class PdfdancerWebsiteSuggestionsConfigTests(unittest.TestCase):
    def test_config_loads_and_references_existing_prompt_files(self) -> None:
        config_path = REPO_ROOT / "config" / "pdfdancer-website-suggestions.yaml"
        validate_backend_prompt_path = REPO_ROOT / "config" / "prompts" / "pdfdancer" / "validate-backend-pr-suggestions.md"
        api_docs_prompt_path = REPO_ROOT / "config" / "prompts" / "pdfdancer" / "implement-api-docs-from-backend-pr.md"
        summarize_api_docs_prompt_path = REPO_ROOT / "config" / "prompts" / "pdfdancer" / "summarize-api-docs-from-backend-pr.md"
        validate_website_prompt_path = REPO_ROOT / "config" / "prompts" / "pdfdancer" / "validate-website-follow-up-context.md"
        website_prompt_path = REPO_ROOT / "config" / "prompts" / "pdfdancer" / "implement-website-from-backend-pr.md"
        summarize_website_prompt_path = REPO_ROOT / "config" / "prompts" / "pdfdancer" / "summarize-website-from-backend-pr.md"

        config = load_config(config_path)

        self.assertEqual(config.version, "6")
        self.assertEqual(tuple(config.repositories), ("pdfdancer-backend", "pdfdancer-api-docs", "pdfdancer-www"))
        self.assertIn("pull_request.labeled", config.signals)
        self.assertIn("issues.labeled", config.signals)
        self.assertEqual(tuple(config.executions), ("implement-approved-api-docs-updates", "implement-approved-website-updates"))
        self.assertEqual(len(config.propagation_triggers), 1)
        self.assertEqual(config.propagation_triggers[0].after, "implement-approved-api-docs-updates")
        self.assertEqual(config.propagation_triggers[0].run, "implement-approved-website-updates")

        api_docs = config.executions["implement-approved-api-docs-updates"]
        self.assertEqual(api_docs.signals[0].signal_name, "pull_request.labeled")
        self.assertEqual(api_docs.signals[0].when, {"repository": "MenschMachine/pdfdancer-backend", "label": "suggestions_needed"})
        self.assertIsNotNone(api_docs.git)
        self.assertEqual(api_docs.before, ['propagate context set :source-backend-pr-number "$(propagate context get :signal.pr_number | xargs)"'])
        self.assertEqual(api_docs.git.branch.name_template, "api-docs/backend-pr-{signal[pr_number]}")
        self.assertEqual(api_docs.git.commit.message_template, "api-docs: document backend PR #{context[:source-backend-pr-number]}")
        self.assertEqual(api_docs.git.pr.body_key, ":api-docs-pr-body")
        self.assertEqual([task.task_id for task in api_docs.sub_tasks], ["validate-backend-pr", "implement", "summarize", "wait-for-verdict", "validate-approved-api-docs-pr"])
        self.assertEqual(
            api_docs.sub_tasks[1].before,
            [
                "git:branch",
            ],
        )
        self.assertEqual(api_docs.sub_tasks[3].before, ["git:publish"])
        self.assertEqual(api_docs.sub_tasks[3].wait_for_signal, "pull_request.labeled")

        website = config.executions["implement-approved-website-updates"]
        self.assertEqual(website.signals, [])
        self.assertIsNotNone(website.git)
        self.assertEqual(
            website.git.branch.name_template,
            "website/backend-pr-{context[implement-approved-api-docs-updates][:source-backend-pr-number]}",
        )
        self.assertEqual(
            website.git.commit.message_template,
            "website: reflect backend PR #{context[implement-approved-api-docs-updates][:source-backend-pr-number]}",
        )
        self.assertEqual(website.git.pr.body_key, ":website-pr-body")
        self.assertEqual([task.task_id for task in website.sub_tasks], ["validate-context", "implement", "summarize"])
        self.assertEqual(
            website.sub_tasks[1].before,
            [
                "git:branch",
            ],
        )
        self.assertEqual(website.after, ["git:publish"])

        validate_backend_prompt = validate_backend_prompt_path.read_text(encoding="utf-8")
        self.assertIn('LABEL` is exactly `suggestions_needed`', validate_backend_prompt)
        self.assertIn('gh pr view "$PR_NUMBER" --repo MenschMachine/pdfdancer-backend', validate_backend_prompt)

        api_docs_prompt = api_docs_prompt_path.read_text(encoding="utf-8")
        self.assertIn("There is no intermediate planning issue", api_docs_prompt)
        self.assertIn('gh pr diff "$PR_NUMBER" --repo MenschMachine/pdfdancer-backend', api_docs_prompt)

        summarize_api_docs_prompt = summarize_api_docs_prompt_path.read_text(encoding="utf-8")
        self.assertIn("## Source Backend PR", summarize_api_docs_prompt)
        self.assertIn("## Website Follow-Up", summarize_api_docs_prompt)
        self.assertNotIn(":api-docs-commit-message", summarize_api_docs_prompt)

        validate_website_prompt = validate_website_prompt_path.read_text(encoding="utf-8")
        self.assertIn(":source-backend-pr-number --task implement-approved-api-docs-updates", validate_website_prompt)
        self.assertIn('SIGNAL_LABEL` is exactly `approved`', validate_website_prompt)

        website_prompt = website_prompt_path.read_text(encoding="utf-8")
        self.assertIn(":api-docs-pr-number --task implement-approved-api-docs-updates", website_prompt)
        self.assertIn("gh pr diff \"$API_DOCS_PR_NUMBER\" --repo MenschMachine/pdfdancer-api-docs", website_prompt)

        summarize_website_prompt = summarize_website_prompt_path.read_text(encoding="utf-8")
        self.assertIn("## Source Backend PR", summarize_website_prompt)
        self.assertIn("## Source API Docs PR", summarize_website_prompt)
        self.assertNotIn(":website-commit-message", summarize_website_prompt)

        for execution in config.executions.values():
            for sub_task in execution.sub_tasks:
                if sub_task.prompt_path is not None:
                    self.assertTrue(sub_task.prompt_path.exists(), sub_task.prompt_path)
                    self.assertTrue(sub_task.prompt_path.is_file(), sub_task.prompt_path)


if __name__ == "__main__":
    unittest.main()
