from __future__ import annotations

import unittest
from pathlib import Path

from propagate import load_config
from propagate_app.models import ContextCondition, ScopedContextKey

REPO_ROOT = Path(__file__).resolve().parents[1]


class PdfdancerCompleteWorkflowConfigTests(unittest.TestCase):
    def test_config_loads_and_resolves_reusable_review_loops(self) -> None:
        config_path = REPO_ROOT / "config" / "pdfdancer-complete-workflow.yaml"
        config = load_config(config_path)

        self.assertEqual(config.version, "6")
        self.assertEqual(
            tuple(config.repositories),
            (
                "pdfdancer-backend",
                "pdfdancer-api",
                "pdfdancer-api-docs",
                "pdfdancer-www",
                "pdfdancer-client-typescript",
                "pdfdancer-client-python",
                "pdfdancer-client-java",
                "pdfdancer-client-typescript-examples",
                "pdfdancer-client-python-examples",
                "pdfdancer-client-java-examples",
            ),
        )
        self.assertIn("pull_request.labeled", config.signals)
        self.assertEqual(
            tuple(config.context_sources),
            ("gommit", "capture-upstream-api-pr", "mark-all-sdks-approved", "mark-all-examples-approved"),
        )

        self.assertEqual(
            tuple(config.executions),
            (
                "implement-pdfdancer-api",
                "implement-client-typescript",
                "implement-client-python",
                "implement-client-java",
                "implement-client-typescript-examples",
                "implement-client-python-examples",
                "implement-client-java-examples",
                "implement-pdfdancer-api-docs",
                "implement-pdfdancer-www",
                "triage-backend-pr",
                "triage-api-pr",
                "assess-complexity-backend",
                "assess-complexity-api",
            ),
        )

        triage = config.executions["triage-backend-pr"]
        self.assertEqual(triage.repository, "pdfdancer-backend")
        self.assertEqual(triage.signals[0].signal_name, "pull_request.labeled")
        self.assertEqual(
            triage.signals[0].when,
            {"repository": "MenschMachine/pdfdancer-backend", "label": "propagate"},
        )
        self.assertEqual([task.task_id for task in triage.sub_tasks], ["validate-backend-pr", "decide-pipeline"])
        self.assertEqual(
            triage.sub_tasks[0].before,
            ["validate:github-pr repo=MenschMachine/pdfdancer-backend pr_from=signal.pr_number"],
        )

        triage_api = config.executions["triage-api-pr"]
        self.assertEqual(triage_api.repository, "pdfdancer-api")
        self.assertEqual(triage_api.signals[0].signal_name, "pull_request.labeled")
        self.assertEqual(
            triage_api.signals[0].when,
            {"repository": "MenschMachine/pdfdancer-api", "label": "propagate"},
        )
        self.assertEqual([task.task_id for task in triage_api.sub_tasks], ["validate-api-pr", "decide-pipeline"])
        self.assertEqual(
            triage_api.sub_tasks[0].before,
            [
                "validate:github-pr repo=MenschMachine/pdfdancer-api pr_from=signal.pr_number",
                "gh pr view \"$(propagate context get :signal.pr_number | xargs)\" --repo MenschMachine/pdfdancer-api --json state --jq '.state' | grep -q '^OPEN$'",
            ],
        )

        api = config.executions["implement-pdfdancer-api"]
        self.assertEqual(api.repository, "pdfdancer-api")
        self.assertEqual(api.git.branch.name_template, "api/backend-pr-{context[triage-backend-pr][:source-backend-pr-number]}")
        self.assertEqual(api.git.pr.number_key, ScopedContextKey(key=":api-pr-number"))
        self.assertEqual(
            [task.task_id for task in api.sub_tasks],
            ["validate-context", "implement", "clear-findings-on-wontfix", "review", "fail-on-upstream-bug", "reroute-on-review-findings", "reroute-on-suggestions", "summarize", "publish", "post-wontfix-comment", "wait-for-checks", "reroute-on-check-failure", "wait-for-verdict"],
        )
        self.assertEqual(api.sub_tasks[5].goto, "implement")
        self.assertEqual(api.sub_tasks[5].max_goto, 3)
        self.assertEqual(api.sub_tasks[6].goto, "implement")
        self.assertEqual(api.sub_tasks[6].on_max_goto, "continue")
        self.assertEqual(api.sub_tasks[11].goto, "implement")
        self.assertEqual(api.sub_tasks[11].max_goto, 3)
        self.assertEqual(api.sub_tasks[12].routes[0].when["repository"], "MenschMachine/pdfdancer-api")
        self.assertEqual(api.sub_tasks[12].routes[0].when["pr_number"], {"equals_context": ":api-pr-number"})

        ts_sdk = config.executions["implement-client-typescript"]
        self.assertEqual(ts_sdk.git.pr.number_key, ScopedContextKey(key=":client-typescript-pr-number"))
        self.assertEqual(ts_sdk.git.branch.name_template, "client-typescript/source-pr-{context[global][:source-pr-number]}")
        self.assertEqual(ts_sdk.after[1], ":mark-all-sdks-approved")

        ts_examples = config.executions["implement-client-typescript-examples"]
        self.assertEqual(ts_examples.git.pr.number_key, ScopedContextKey(key=":client-typescript-examples-pr-number"))
        self.assertEqual(ts_examples.after[1], ":mark-all-examples-approved")

        api_docs = config.executions["implement-pdfdancer-api-docs"]
        self.assertEqual(api_docs.git.pr.number_key, ScopedContextKey(key=":api-docs-pr-number"))
        website = config.executions["implement-pdfdancer-www"]
        self.assertEqual(website.git.pr.number_key, ScopedContextKey(key=":website-pr-number"))

        self.assertEqual(len(config.propagation_triggers), 24)
        triage_to_assess_backend = next(t for t in config.propagation_triggers if t.after == "triage-backend-pr" and t.run == "assess-complexity-backend")
        self.assertIsNone(triage_to_assess_backend.when_context)
        assess_backend_to_api = next(t for t in config.propagation_triggers if t.after == "assess-complexity-backend" and t.run == "implement-pdfdancer-api")
        self.assertIsNone(assess_backend_to_api.when_context)
        assess_backend_to_docs = next(t for t in config.propagation_triggers if t.after == "assess-complexity-backend" and t.run == "implement-pdfdancer-api-docs")
        self.assertIsNone(assess_backend_to_docs.when_context)
        triage_to_assess_api = next(t for t in config.propagation_triggers if t.after == "triage-api-pr" and t.run == "assess-complexity-api")
        self.assertIsNone(triage_to_assess_api.when_context)
        assess_api_to_ts = next(t for t in config.propagation_triggers if t.after == "assess-complexity-api" and t.run == "implement-client-typescript")
        self.assertIsNone(assess_api_to_ts.when_context)
        assess_api_to_docs = next(t for t in config.propagation_triggers if t.after == "assess-complexity-api" and t.run == "implement-pdfdancer-api-docs")
        self.assertIsNone(assess_api_to_docs.when_context)

        example_trigger = next(
            t for t in config.propagation_triggers
            if t.after == "implement-client-java" and t.run == "implement-client-python-examples"
        )
        self.assertEqual(example_trigger.when_context, ContextCondition(ref=ScopedContextKey(key=":all-sdks-approved")))

        docs_trigger = next(
            t for t in config.propagation_triggers
            if t.after == "implement-client-java-examples" and t.run == "implement-pdfdancer-api-docs"
        )
        self.assertEqual(docs_trigger.when_context, ContextCondition(ref=ScopedContextKey(key=":all-examples-approved")))

        for prompt_path in [
            REPO_ROOT / "config" / "prompts" / "pdfdancer" / "decide-backend-pipeline.md",
            REPO_ROOT / "config" / "prompts" / "pdfdancer" / "validate-api-pr-trigger.md",
            REPO_ROOT / "config" / "prompts" / "pdfdancer" / "decide-api-pipeline.md",
            REPO_ROOT / "config" / "prompts" / "pdfdancer" / "implement-api-from-backend-pr.md",
            REPO_ROOT / "config" / "prompts" / "pdfdancer" / "implement-client-sdk-from-api-pr.md",
            REPO_ROOT / "config" / "prompts" / "pdfdancer" / "implement-client-typescript-examples-from-sdk-pr.md",
            REPO_ROOT / "config" / "prompts" / "pdfdancer" / "implement-client-python-examples-from-sdk-pr.md",
            REPO_ROOT / "config" / "prompts" / "pdfdancer" / "implement-client-java-examples-from-sdk-pr.md",
            REPO_ROOT / "config" / "prompts" / "pdfdancer" / "implement-api-docs-from-workflow-context.md",
            REPO_ROOT / "config" / "prompts" / "pdfdancer" / "implement-website-from-workflow-context.md",
            REPO_ROOT / "config" / "prompts" / "pdfdancer" / "assess-complexity.md",
        ]:
            self.assertTrue(prompt_path.exists(), prompt_path)


if __name__ == "__main__":
    unittest.main()
