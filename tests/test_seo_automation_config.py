from __future__ import annotations

import unittest
from pathlib import Path

from propagate import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


class SeoAutomationConfigTests(unittest.TestCase):
    def test_config_loads_with_strategy_brief_and_split_implementation_lanes(self) -> None:
        config_path = REPO_ROOT / "config" / "seo-automation.yaml"
        config = load_config(config_path)

        self.assertEqual(config.version, "6")
        self.assertEqual(tuple(config.repositories), ("pdfdancer-marketing-data", "pdfdancer-www"))
        self.assertEqual(
            tuple(config.executions),
            (
                "pull-data",
                "enrich-seo",
                "evaluate-implementations",
                "intent-match",
                "analyze",
                "plan-seo",
                "brief-rewrites",
                "brief-new-content",
                "implement-rewrites",
                "implement-new-content",
                "track-implementations",
                "request-index",
            ),
        )

        plan = config.executions["plan-seo"]
        self.assertEqual(plan.repository, "pdfdancer-marketing-data")
        self.assertEqual(
            [task.task_id for task in plan.sub_tasks],
            ["set-branch", "create-branch", "strategy", "review-plan", "reroute-on-review-findings", "summarize", "publish", "wait-for-verdict", "route-after-approval"],
        )
        self.assertEqual(plan.sub_tasks[4].goto, "strategy")
        self.assertNotIn("propagate context delete :review-findings", plan.sub_tasks[2].before)
        self.assertNotIn("propagate context delete :review-suggestions", plan.sub_tasks[2].before)
        self.assertIn("propagate context set :plan-approved-rewrites true", plan.sub_tasks[8].before[0])

        brief_rewrites = config.executions["brief-rewrites"]
        self.assertEqual(brief_rewrites.repository, "pdfdancer-marketing-data")
        self.assertEqual(brief_rewrites.sub_tasks[2].must_set, [":rewrite-briefs-path", ":rewrite-briefs"])
        self.assertNotIn("propagate context delete :review-findings", brief_rewrites.sub_tasks[2].before)
        self.assertNotIn("propagate context delete :review-suggestions", brief_rewrites.sub_tasks[2].before)
        self.assertEqual(brief_rewrites.sub_tasks[-1].task_id, "route-after-approval")
        self.assertEqual(brief_rewrites.sub_tasks[-1].before, ["propagate context set :rewrite-briefs-approved true"])

        brief_new = config.executions["brief-new-content"]
        self.assertEqual(brief_new.repository, "pdfdancer-marketing-data")
        self.assertEqual(brief_new.sub_tasks[2].must_set, [":new-content-briefs-path", ":new-content-briefs"])
        self.assertNotIn("propagate context delete :review-findings", brief_new.sub_tasks[2].before)
        self.assertNotIn("propagate context delete :review-suggestions", brief_new.sub_tasks[2].before)
        self.assertEqual(brief_new.sub_tasks[-1].task_id, "route-after-approval")
        self.assertEqual(brief_new.sub_tasks[-1].before, ["propagate context set :new-content-briefs-approved true"])

        implement_rewrites = config.executions["implement-rewrites"]
        self.assertEqual(implement_rewrites.repository, "pdfdancer-www")
        self.assertEqual(implement_rewrites.sub_tasks[2].must_set, [":changed-urls-rewrites"])
        self.assertEqual(implement_rewrites.sub_tasks[4].goto, "code")
        self.assertEqual(implement_rewrites.sub_tasks[4].max_goto, 5)
        self.assertNotIn("propagate context delete :review-findings", implement_rewrites.sub_tasks[2].before)
        self.assertNotIn("propagate context delete :review-suggestions", implement_rewrites.sub_tasks[2].before)

        implement_new = config.executions["implement-new-content"]
        self.assertEqual(implement_new.repository, "pdfdancer-www")
        self.assertEqual(implement_new.sub_tasks[2].must_set, [":changed-urls-new-content"])
        self.assertEqual(implement_new.sub_tasks[4].goto, "code")
        self.assertEqual(implement_new.sub_tasks[4].max_goto, 5)
        self.assertNotIn("propagate context delete :review-findings", implement_new.sub_tasks[2].before)
        self.assertNotIn("propagate context delete :review-suggestions", implement_new.sub_tasks[2].before)

        triggers = {(t.after, t.run, t.when_context) for t in config.propagation_triggers}
        self.assertIn(("analyze", "plan-seo", None), triggers)
        self.assertIn(("plan-seo", "brief-rewrites", ":plan-approved-rewrites"), triggers)
        self.assertIn(("plan-seo", "brief-new-content", ":plan-approved-new-content-direct"), triggers)
        self.assertIn(("brief-rewrites", "implement-rewrites", ":rewrite-briefs-approved"), triggers)
        self.assertIn(("implement-rewrites", "brief-new-content", ":run-new-content-after-rewrites"), triggers)
        self.assertIn(("implement-rewrites", "track-implementations", ":ready-to-track"), triggers)
        self.assertIn(("brief-new-content", "implement-new-content", ":new-content-briefs-approved"), triggers)
        self.assertIn(("implement-new-content", "track-implementations", ":ready-to-track"), triggers)

        for prompt_path in [
            REPO_ROOT / "config" / "prompts" / "seo" / "plan-seo.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "review-plan.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "summarize-plan-seo.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "brief-rewrites.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "review-briefs-rewrites.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "summarize-brief-rewrites.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "brief-new-content.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "review-briefs-new-content.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "summarize-brief-new-content.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "implement-rewrites.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "review-implement-rewrites.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "revise-briefs-rewrites.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "summarize-implement-rewrites.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "implement-new-content.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "review-implement-new-content.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "revise-briefs-new-content.md",
            REPO_ROOT / "config" / "prompts" / "seo" / "summarize-implement-new-content.md",
        ]:
            self.assertTrue(prompt_path.exists(), prompt_path)

    def test_briefing_prompts_enforce_reader_question_not_template_contract(self) -> None:
        brief_rewrites = (REPO_ROOT / "config" / "prompts" / "seo" / "brief-rewrites.md").read_text(encoding="utf-8")
        brief_new = (REPO_ROOT / "config" / "prompts" / "seo" / "brief-new-content.md").read_text(encoding="utf-8")
        revise_rewrites = (REPO_ROOT / "config" / "prompts" / "seo" / "revise-briefs-rewrites.md").read_text(encoding="utf-8")
        review_rewrites = (REPO_ROOT / "config" / "prompts" / "seo" / "review-briefs-rewrites.md").read_text(encoding="utf-8")

        self.assertIn("`core_reader_questions`", brief_rewrites)
        self.assertIn("Do not require a fixed section list.", brief_rewrites)
        self.assertIn("Do not prescribe generic section templates", brief_rewrites)

        self.assertIn("Do not solve the problem by prescribing a generic launch-page structure.", brief_new)
        self.assertIn("replace templated section instructions with page promise, core reader questions, proof, and editorial guardrails", revise_rewrites)
        self.assertIn("do they avoid prescribing a generic section template", review_rewrites)


if __name__ == "__main__":
    unittest.main()
