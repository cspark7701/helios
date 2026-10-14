"""Tests for GitHub Actions CI workflow, contract, and local pre-push checking scripts."""

import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_FILE = ROOT / ".github/workflows/ci.yml"
CONTRACT_FILE = ROOT / ".github/ci-contract.json"
CHECK_SCRIPT = ROOT / "scripts/check_github_actions.sh"
CI_CONTRACT_SCRIPT = ROOT / "scripts/ci_contract.py"


def test_ci_workflow_yaml_validity():
    """Verify that .github/workflows/ci.yml exists, is valid YAML, and has expected jobs."""
    assert WORKFLOW_FILE.exists(), f"Missing workflow file at {WORKFLOW_FILE}"

    data = yaml.safe_load(WORKFLOW_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data.get("name") == "HELIOS CI"

    # Verify triggers (PyYAML parses 'on:' as boolean True or string 'on')
    triggers = data.get("on") or data.get(True)
    assert triggers is not None
    assert "push" in triggers
    assert "pull_request" in triggers

    # Verify jobs
    jobs = data.get("jobs", {})
    assert "build-test" in jobs
    assert "package-verification" in jobs


def test_ci_contract_json_validity():
    """Verify .github/ci-contract.json schema and matrix versions."""
    assert CONTRACT_FILE.exists(), f"Missing contract file at {CONTRACT_FILE}"

    data = json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))
    assert "python_versions" in data
    assert "3.11" in data["python_versions"]
    assert "3.13" in data["python_versions"]
    assert "3.14" in data["python_versions"]
    assert "extras" in data
    assert "checks" in data
    assert len(data["checks"]) >= 2


def test_ci_contract_validate_command():
    """Verify scripts/ci_contract.py validate action executes successfully."""
    cmd = [sys.executable, str(CI_CONTRACT_SCRIPT), "validate"]
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0
    assert "Workflow ci.yml parsed successfully" in res.stdout


def test_ci_contract_matrix_generation():
    """Verify scripts/ci_contract.py matrix action returns valid JSON."""
    cmd = [sys.executable, str(CI_CONTRACT_SCRIPT), "matrix"]
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0
    matrix = json.loads(res.stdout)
    assert "python-version" in matrix
    assert isinstance(matrix["python-version"], list)


def test_check_github_actions_script_executable():
    """Verify scripts/check_github_actions.sh exists and is executable."""
    assert CHECK_SCRIPT.exists()
    assert os.access(CHECK_SCRIPT, os.X_OK), f"{CHECK_SCRIPT} is not executable"


def test_local_ci_dry_run_execution():
    """Verify ./scripts/check_github_actions.sh --dry-run completes cleanly with code 0."""
    res = subprocess.run([str(CHECK_SCRIPT), "--dry-run"], cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0
    assert "HELIOS LOCAL PRE-PUSH CI CHECK" in res.stdout
    assert "ALL LOCAL CI CHECKS PASSED SUCCESSFULLY" in res.stdout


def test_execution_plan_ids_unique():
    """Verify that all execution plans in docs/exec-plans/ have unique 5-digit IDs and INDEX.md exists."""
    import re

    exec_plans_dir = ROOT / "docs" / "exec-plans"
    index_file = exec_plans_dir / "INDEX.md"
    assert index_file.exists(), f"Missing plan registry index at {index_file}"

    plan_files = list((exec_plans_dir / "active").glob("*.md")) + list(
        (exec_plans_dir / "completed").glob("*.md")
    )
    seen_ids: dict[str, Path] = {}
    duplicates: list[tuple[str, Path, Path]] = []

    for p in plan_files:
        m = re.match(r"^(\d{5})_", p.name)
        if not m:
            continue
        plan_id = m.group(1)
        if plan_id in seen_ids:
            duplicates.append((plan_id, seen_ids[plan_id], p))
        else:
            seen_ids[plan_id] = p

    assert len(duplicates) == 0, f"Duplicate plan IDs found: {duplicates}"
    assert len(seen_ids) >= 40, f"Expected >=40 plans, found {len(seen_ids)}"

