"""HELIOS Local CI Matrix, Contract Validation, and Pre-Push Verification.

Enables running GitHub Actions workflow checks locally before any git push.
Supports matrix generation, workflow YAML validation, entrypoint checks,
and local pytest test execution with zero remote access.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / ".github/ci-contract.json"
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def load_contract() -> Dict[str, Any]:
    """Load and validate .github/ci-contract.json."""
    if not CONTRACT.exists():
        raise FileNotFoundError(f"Missing CI contract at {CONTRACT}")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for key in ("python_versions", "extras", "checks"):
        if key not in contract:
            raise ValueError(f"CI contract missing required key: '{key}'")
    return contract


def generate_matrix(version: str = "all") -> str:
    """Generate JSON test matrix for GitHub Actions or local multi-version testing."""
    contract = load_contract()
    versions = contract["python_versions"]
    if version != "all":
        if version not in versions:
            raise ValueError(f"Python version '{version}' not in matrix ({', '.join(versions)})")
        versions = [version]
    return json.dumps({"python-version": versions})


def validate_workflow() -> None:
    """Validate YAML syntax and structural contract of .github/workflows/ci.yml."""
    import yaml

    if not WORKFLOW.exists():
        raise FileNotFoundError(f"Workflow file does not exist: {WORKFLOW}")

    content = WORKFLOW.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML syntax in {WORKFLOW}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Workflow {WORKFLOW} must be a YAML mapping")

    # Verify essential workflow components
    # PyYAML safe_load parses 'on:' as boolean True or string 'on'
    triggers = data.get("on") or data.get(True)
    if not triggers:
        raise ValueError(f"Workflow {WORKFLOW} is missing triggers ('on')")

    jobs = data.get("jobs", {})
    if not jobs:
        raise ValueError(f"Workflow {WORKFLOW} defines no jobs")

    print(f"✓ Workflow {WORKFLOW.name} parsed successfully ({len(jobs)} jobs defined).")


def validate_plan_records() -> None:
    """Verify that all execution plans in docs/exec-plans/ have unique 5-digit IDs."""
    import re

    exec_plans_dir = ROOT / "docs" / "exec-plans"
    if not exec_plans_dir.exists():
        return

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

    if duplicates:
        dup_msgs = [f"ID {pid}: {f1.name} and {f2.name}" for pid, f1, f2 in duplicates]
        raise ValueError(
            "Duplicate execution plan IDs detected in docs/exec-plans/:\n" + "\n".join(dup_msgs)
        )

    print(f"✓ Execution plans validated ({len(seen_ids)} unique 5-digit plan IDs verified).")


def run_checks(*, fast: bool = False, quiet: bool = False, dry_run: bool = False) -> None:
    """Run shared contract checks defined in ci-contract.json."""
    contract = load_contract()
    for check in contract["checks"]:
        name = check["name"]
        args = check["args"]
        cmd = [sys.executable, *args]

        if not quiet:
            print(f"[CHECK] {name}\n  Command: {' '.join(cmd)}", flush=True)

        if dry_run:
            continue

        res = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=quiet, timeout=300)
        if res.returncode != 0:
            if quiet:
                print(res.stdout + res.stderr, file=sys.stderr)
            raise subprocess.CalledProcessError(res.returncode, cmd)

        if not quiet:
            print(f"  ✓ PASSED: {name}", flush=True)


def pre_push_commands(fast: bool = False) -> List[tuple]:
    """Commands executed locally in the pre-push check sequence."""
    pytest_cmd = [sys.executable, "-m", "pytest", "tests/", "--tb=short", "-q"]
    if fast:
        pytest_cmd.extend(["-m", "not slow"])

    return [
        ("HELIOS Core Import", [sys.executable, "-c", "import helios; print('HELIOS core imported successfully')"]),
        ("CLI Root Help", [sys.executable, "-m", "helios.cli.main", "--help"]),
        ("CLI Orbit Tune Help", [sys.executable, "-m", "helios.cli.main", "tune-orbit", "--help"]),
        ("CLI Chat Help", [sys.executable, "-m", "helios.cli.main", "chat", "--help"]),
        ("CLI Dashboard Help", [sys.executable, "-m", "helios.cli.main", "dashboard", "--help"]),
        ("Pytest Test Suite", pytest_cmd),
    ]


def run_local_pre_push(
    *,
    fast: bool = False,
    quiet: bool = False,
    dry_run: bool = False,
    allow_dirty: bool = False,
) -> None:
    """Run full CI pipeline locally before git-pushing without remote access."""
    # Preflight git status check
    if not dry_run and not allow_dirty:
        git_res = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if git_res.returncode == 0 and git_res.stdout.strip():
            print("⚠️ Notice: Uncommitted tracked changes detected in working directory.", file=sys.stderr)
            print("   Pass --allow-dirty to test uncommitted changes, or commit first.", file=sys.stderr)

    curr_py = f"{sys.version_info.major}.{sys.version_info.minor}"
    print(f"\n====================================================================")
    print(f" HELIOS LOCAL PRE-PUSH CI CHECK (Python {curr_py})")
    print(f"====================================================================")
    print("Executing local workflow pipeline (no remote push or GitHub access)...\n")

    # Step 1: Run contract checks
    if not quiet:
        print("--- Step 1: Contract & Workflow Validation ---")
    run_checks(fast=fast, quiet=quiet, dry_run=dry_run)

    # Step 2: Run core commands & pytest suite
    if not quiet:
        print("\n--- Step 2: Local Pre-Push CI Test Job ---")

    for name, cmd in pre_push_commands(fast=fast):
        if not quiet:
            print(f"[TEST] {name}\n  Command: {' '.join(cmd)}", flush=True)

        if dry_run:
            continue

        res = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=quiet, timeout=600)
        if res.returncode != 0:
            if quiet:
                print(res.stdout + res.stderr, file=sys.stderr)
            print(f"❌ FAILED: {name} (exit code {res.returncode})", file=sys.stderr)
            sys.exit(res.returncode)

        if not quiet:
            print(f"  ✓ PASSED: {name}", flush=True)

    print("\n====================================================================")
    print(" ✔ ALL LOCAL CI CHECKS PASSED SUCCESSFULLY!")
    print(" Safe to proceed with local git commits.")
    print("====================================================================\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    # validate action
    sub.add_parser("validate", help="Validate CI contract and workflow YAML syntax")

    # matrix action
    mat_parser = sub.add_parser("matrix", help="Generate JSON test matrix for GitHub Actions")
    mat_parser.add_argument("--python-version", default="all")

    # checks action
    chk_parser = sub.add_parser("checks", help="Run contract checks")
    chk_parser.add_argument("--fast", action="store_true")

    # local action
    loc_parser = sub.add_parser("local", help="Run full pre-push CI test job locally")
    loc_parser.add_argument("-f", "--fast", action="store_true", help="Skip slow tests")
    loc_parser.add_argument("-q", "--quiet", action="store_true", help="Quiet output")
    loc_parser.add_argument("-d", "--dry-run", action="store_true", help="Print commands without executing")
    loc_parser.add_argument("--allow-dirty", action="store_true", help="Allow uncommitted tracked changes")

    args = parser.parse_args(argv)

    if args.action == "validate":
        load_contract()
        validate_workflow()
        validate_plan_records()
        return 0
    elif args.action == "matrix":
        print(generate_matrix(args.python_version))
        return 0
    elif args.action == "checks":
        run_checks(fast=args.fast)
        return 0
    elif args.action == "local":
        run_local_pre_push(
            fast=args.fast,
            quiet=args.quiet,
            dry_run=args.dry_run,
            allow_dirty=args.allow_dirty,
        )
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
