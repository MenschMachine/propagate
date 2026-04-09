from pathlib import Path

from propagate import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_config_loads_with_single_plan_and_single_implementation_lane() -> None:
    config = load_config(REPO_ROOT / "config" / "seo-automation.yaml")

    assert config.version == "6"
    assert tuple(config.repositories) == ("pdfdancer-marketing-data", "pdfdancer-www")
    assert tuple(config.executions) == (
        "pull-data",
        "enrich-seo",
        "evaluate-implementations",
        "intent-match",
        "analyze",
        "plan-seo",
        "implement-seo",
        "track-implementations",
        "request-index",
    )

    plan = config.executions["plan-seo"]
    assert plan.repository == "pdfdancer-marketing-data"
    assert [task.task_id for task in plan.sub_tasks] == [
        "set-branch",
        "create-branch",
        "strategy",
        "review-plan",
        "reroute-on-review-findings",
        "summarize",
        "publish",
        "wait-for-verdict",
        "route-after-approval",
    ]
    assert plan.sub_tasks[2].must_set == [
        ":strategy-path",
        ":implementation-briefs-path",
        ":implementation-briefs",
        ":implementation-targets",
    ]
    assert "propagate context delete :plan-approved" in plan.sub_tasks[2].before
    assert "propagate context delete :review-findings" in plan.sub_tasks[2].before
    assert "propagate context delete :review-suggestions" in plan.sub_tasks[2].before
    assert "propagate context delete :revision-reason" in plan.sub_tasks[2].before
    assert plan.sub_tasks[4].goto == "strategy"
    assert "propagate context set :plan-approved true" in plan.sub_tasks[8].before[0]

    implement = config.executions["implement-seo"]
    assert implement.repository == "pdfdancer-www"
    assert [task.task_id for task in implement.sub_tasks] == [
        "set-branch",
        "create-branch",
        "code",
        "review",
        "reroute-on-implementation-findings",
        "flag-brief-problem",
        "revise-briefs",
        "reroute-after-brief-revision",
        "summarize",
        "publish",
        "wait-for-checks",
        "reroute-on-check-failure",
        "wait-for-verdict",
        "route-after-approval",
    ]
    assert implement.sub_tasks[2].must_set == [":changed-urls"]
    assert "propagate context delete :ready-to-track" in implement.sub_tasks[2].before
    assert "propagate context delete :active-implementation-briefs" in implement.sub_tasks[2].before
    assert "propagate context delete :review-findings" in implement.sub_tasks[2].before
    assert "propagate context delete :review-suggestions" in implement.sub_tasks[2].before
    assert "propagate context delete :review-findings-brief" in implement.sub_tasks[2].before
    assert "propagate context delete :revision-reason" in implement.sub_tasks[2].before
    assert implement.sub_tasks[4].goto == "code"
    assert implement.sub_tasks[4].max_goto == 5
    assert implement.sub_tasks[7].goto == "code"
    assert implement.sub_tasks[7].max_goto == 5

    triggers = {(t.after, t.run, t.when_context) for t in config.propagation_triggers}
    assert ("analyze", "plan-seo", None) in triggers
    assert ("plan-seo", "implement-seo", ":plan-approved") in triggers
    assert ("implement-seo", "track-implementations", ":ready-to-track") in triggers
    assert ("track-implementations", "request-index", None) in triggers

    for prompt_path in [
        REPO_ROOT / "config" / "prompts" / "seo" / "plan-seo.md",
        REPO_ROOT / "config" / "prompts" / "seo" / "review-plan.md",
        REPO_ROOT / "config" / "prompts" / "seo" / "summarize-plan-seo.md",
        REPO_ROOT / "config" / "prompts" / "seo" / "implement.md",
        REPO_ROOT / "config" / "prompts" / "seo" / "review-implement.md",
        REPO_ROOT / "config" / "prompts" / "seo" / "revise-briefs.md",
        REPO_ROOT / "config" / "prompts" / "seo" / "summarize-implement.md",
        REPO_ROOT / "config" / "prompts" / "seo" / "track-implementations.md",
    ]:
        assert prompt_path.exists(), prompt_path

    pull_data = config.executions["pull-data"]
    fetch_data = pull_data.sub_tasks[1]
    assert "propagate context set --global :gsc-data-path \"$(propagate context get :gsc-data-path)\"" in fetch_data.before
    assert "propagate context set --global :posthog-data-path \"$(propagate context get :posthog-data-path)\"" in fetch_data.before

    evaluate = config.executions["evaluate-implementations"].sub_tasks[0]
    assert "propagate context set --global :evaluation-results \"$(propagate context get :evaluation-results)\"" in evaluate.before


def test_plan_and_implementation_prompts_enforce_simple_typed_brief_contract() -> None:
    plan = (REPO_ROOT / "config" / "prompts" / "seo" / "plan-seo.md").read_text(encoding="utf-8")
    review_plan = (REPO_ROOT / "config" / "prompts" / "seo" / "review-plan.md").read_text(encoding="utf-8")
    implement = (REPO_ROOT / "config" / "prompts" / "seo" / "implement.md").read_text(encoding="utf-8")
    revise = (REPO_ROOT / "config" / "prompts" / "seo" / "revise-briefs.md").read_text(encoding="utf-8")
    review_implement = (REPO_ROOT / "config" / "prompts" / "seo" / "review-implement.md").read_text(encoding="utf-8")
    track = (REPO_ROOT / "config" / "prompts" / "seo" / "track-implementations.md").read_text(encoding="utf-8")

    assert "Produce two artifacts" in plan
    assert "`implementation-briefs.yaml`" in plan
    assert "`change_type`" in plan
    assert "`core_reader_questions`" in plan
    assert "Do not split this into separate rewrite and new-content handoff files." in plan

    assert "whether the implementation briefs are actually writable" in review_plan
    assert "approved briefs" in implement
    assert "Decide: edit vs create" in implement
    assert "propagate context get :implementation-briefs --task plan-seo" in implement
    assert "preserve the approved targets and overall strategic intent" in revise
    assert "Implementation problem" in review_implement
    assert "Brief problem" in review_implement
    assert "propagate context get :changed-urls --task implement-seo" in track
    assert "propagate context get :implementation-briefs --task plan-seo" in track
    assert 'find reports/ -name "implementation-briefs.yaml"' in track


def test_seo_prompts_use_global_scope_for_shared_data_handoff_keys() -> None:
    pull_summary = (REPO_ROOT / "config" / "prompts" / "seo" / "pull-data-summary.md").read_text(encoding="utf-8")
    analyze = (REPO_ROOT / "config" / "prompts" / "seo" / "analyze.md").read_text(encoding="utf-8")
    intent_match = (REPO_ROOT / "config" / "prompts" / "seo" / "intent-match.md").read_text(encoding="utf-8")

    assert "propagate context get --global :gsc-data-path" in pull_summary
    assert "propagate context get --global :posthog-data-path" in pull_summary

    assert "propagate context get --global :gsc-data-path" in analyze
    assert "propagate context get --global :posthog-data-path" in analyze
    assert "propagate context get --global :evaluation-results" in analyze

    assert "propagate context get --global :gsc-data-path" in intent_match
    assert "propagate context get --global :posthog-data-path" in intent_match
