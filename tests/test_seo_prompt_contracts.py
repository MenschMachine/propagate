from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_analyze_prompt_is_history_aware_and_groups_outputs() -> None:
    prompt = (REPO_ROOT / "config" / "prompts" / "seo" / "analyze.md").read_text()

    assert "SEO Implementation History (Required):" in prompt
    assert "history_state" in prompt
    assert "## Implementation Follow-Ups" in prompt
    assert "top_new_findings:" in prompt
    assert "implementation_follow_ups:" in prompt
    assert "deferred_or_low_confidence:" in prompt


def test_create_issues_prompt_consumes_grouped_findings_safely() -> None:
    prompt = (REPO_ROOT / "config" / "prompts" / "seo" / "create-issues.md").read_text()

    assert "top_new_findings" in prompt
    assert "implementation_follow_ups" in prompt
    assert "deferred_or_low_confidence" in prompt
    assert "create issues only from `top_new_findings`" in prompt
    assert "never create issues from `deferred_or_low_confidence`" in prompt
