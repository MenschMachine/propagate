"""Regression tests for setup-script label extraction with execution includes."""

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

_spec = spec_from_file_location("propagate_setup", SCRIPTS_DIR / "propagate-setup.py")
_mod = module_from_spec(_spec)
_spec.loader.exec_module(_mod)

extract_labels = _mod.extract_labels


def test_extract_labels_resolves_execution_includes_for_pdfdancer_workflow():
    config_path = REPO_ROOT / "config" / "pdfdancer-complete-workflow.yaml"
    with config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    labels = extract_labels(config, config_path.parent)

    assert labels == ["approved", "changes_required"]
