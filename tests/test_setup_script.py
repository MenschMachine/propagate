"""Tests for scripts/propagate-setup.py helpers."""

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

_spec = spec_from_file_location("propagate_setup", SCRIPTS_DIR / "propagate-setup.py")
_mod = module_from_spec(_spec)
_spec.loader.exec_module(_mod)

extract_labels = _mod.extract_labels


def test_extract_labels_includes_execution_signal_filters():
    config = {
        "executions": {
            "suggest": {
                "signals": [
                    {
                        "signal": "pull_request.labeled",
                        "when": {"label": "suggestions_needed"},
                    }
                ],
                "sub_tasks": [],
            },
            "implement": {
                "signals": [
                    {
                        "signal": "issues.labeled",
                        "when": {"label": "approved"},
                    }
                ],
                "sub_tasks": [],
            },
        }
    }

    assert extract_labels(config) == ["approved", "suggestions_needed"]


def test_extract_labels_includes_prompt_annotations(tmp_path):
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(
        "# Prompt\n\n<!-- propagate-required-labels: website_suggestions, docs_review -->\n",
        encoding="utf-8",
    )
    config = {
        "executions": {
            "suggest": {
                "sub_tasks": [{"prompt": "./prompt.md"}],
            }
        }
    }

    assert extract_labels(config, tmp_path) == ["docs_review", "website_suggestions"]


def test_setup_help_shows_issues_in_default_event_list():
    source = (SCRIPTS_DIR / "propagate-setup.py").read_text(encoding="utf-8")

    assert 'default="push,pull_request,issues,issue_comment"' in source


def test_prod_setup_help_shows_issues_in_default_event_list():
    source = (SCRIPTS_DIR / "propagate-prod-setup.py").read_text(encoding="utf-8")

    assert 'default="push,pull_request,issues,issue_comment"' in source
