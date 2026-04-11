from pathlib import Path

from propagate import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_config_loads_with_simplified_pipeline() -> None:
    config = load_config(REPO_ROOT / "config" / "seo-automation.yaml")

    assert config.version == "6"
    assert tuple(config.repositories) == ("pdfdancer-marketing-data", "pdfdancer-www")
    assert tuple(config.executions) == (
        "pull-data",
        "enrich-seo",
        "intent-match",
        "analyze",
        "create-issues",
    )

    create_issues = config.executions["create-issues"]
    assert create_issues.repository == "pdfdancer-www"
    assert [task.task_id for task in create_issues.sub_tasks] == ["create-issues"]

    triggers = {(t.after, t.run, t.when_context) for t in config.propagation_triggers}
    assert ("pull-data", "intent-match", None) in triggers
    assert ("intent-match", "analyze", None) in triggers
    assert ("analyze", "create-issues", None) in triggers
    assert len(config.propagation_triggers) == 3

    assert (REPO_ROOT / "config" / "prompts" / "seo" / "create-issues.md").exists()

    pull_data = config.executions["pull-data"]
    fetch_data = pull_data.sub_tasks[2]
    assert "propagate context set --global :gsc-data-path \"$(propagate context get :gsc-data-path)\"" in fetch_data.before
    assert "propagate context set --global :posthog-data-path \"$(propagate context get :posthog-data-path)\"" in fetch_data.before


def test_create_issues_prompt_structure() -> None:
    prompt = (REPO_ROOT / "config" / "prompts" / "seo" / "create-issues.md").read_text(encoding="utf-8")

    assert "propagate context get --global :findings" in prompt
    assert "gh issue list" in prompt
    assert "gh issue create" in prompt
    assert "MenschMachine/pdfdancer-www" in prompt
    assert "duplicate" in prompt.lower()
    assert "defer" in prompt


def test_seo_create_issues_prompt_uses_global_findings() -> None:
    prompt = (REPO_ROOT / "config" / "prompts" / "seo" / "create-issues.md").read_text(encoding="utf-8")
    assert "propagate context get --global :findings" in prompt
