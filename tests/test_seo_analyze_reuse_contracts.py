from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_analyze_execution_reuses_existing_daily_report_and_findings() -> None:
    execution = (REPO_ROOT / "config" / "executions" / "seo" / "analyze.yaml").read_text()

    assert "- id: check-existing-data" in execution
    assert 'if [ -f "reports/$TODAY/report.md" ]' in execution
    assert 'propagate context set --stdin --global :report < "reports/$TODAY/report.md"' in execution
    assert 'if [ -f "reports/$TODAY/findings.yaml" ]' in execution
    assert 'propagate context set --stdin --global :findings < "reports/$TODAY/findings.yaml"' in execution
    assert 'propagate context set :report-exists "true"' in execution
    assert 'when: "!:report-exists"' in execution


def test_analyze_prompt_persists_findings_for_later_reuse() -> None:
    prompt = (REPO_ROOT / "config" / "prompts" / "seo" / "analyze.md").read_text()

    assert "Write `reports/YYYY-MM-DD/findings.yaml`" in prompt
    assert "Save the same YAML payload to `reports/YYYY-MM-DD/findings.yaml`" in prompt