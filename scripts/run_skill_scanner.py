#!/usr/bin/env python3
"""Run NVIDIA SkillEvaluator Tier 1 (--no-llm) across all public skills.

Intended for merge-time validation (merge_group, push to main, or manual audit)
rather than routine pull-request or local edit loops. Only the target skills
root (default: repository skills/) is scanned; skills-local is never read by
default.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILLS_ROOT = REPO_ROOT / "skills"
DEFAULT_BASELINE = REPO_ROOT / ".github" / "skillspector-baseline.yaml"
BYTECODE_SUFFIXES = (".pyc", ".pyo")


def resolve_scanner_binary(binary: str) -> str | None:
    if os.sep in binary or (os.altsep and os.altsep in binary):
        candidate = Path(binary)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        return None
    found = shutil.which(binary)
    return str(Path(found).resolve()) if found else None


def find_bytecode_artifacts(root: Path) -> list[Path]:
    offenders: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(current_root)
        for dirname in sorted(dirnames):
            if dirname == "__pycache__":
                offenders.append(current / dirname)
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in sorted(filenames):
            if filename.endswith(BYTECODE_SUFFIXES):
                offenders.append(current / filename)
    return offenders


def validate_tree_hygiene(skills_root: Path) -> tuple[list[Path], list[str]]:
    errors: list[str] = []
    try:
        resolved_root = skills_root.resolve(strict=True)
    except OSError as exc:
        return [], [f"{skills_root}: skills root could not be resolved ({exc})"]
    if not resolved_root.is_dir():
        return [], [f"{resolved_root}: skills root is not a directory"]

    for current_root, dirnames, filenames in os.walk(resolved_root, followlinks=False):
        current = Path(current_root)
        for name in sorted(dirnames + filenames):
            candidate = current / name
            if os.path.islink(candidate):
                if not os.path.exists(candidate):
                    errors.append(f"{candidate}: broken symlink inside skills root")
                    continue
                target = Path(os.path.realpath(candidate))
                if not target.is_relative_to(resolved_root):
                    errors.append(
                        f"{candidate}: symlink escapes skills root -> {target}"
                    )

    for offender in find_bytecode_artifacts(resolved_root):
        errors.append(f"{offender}: stray Python bytecode under skills root")

    skill_dirs: list[Path] = []
    for child in sorted(resolved_root.iterdir()):
        if child.name.startswith((".", "_")):
            continue
        if os.path.islink(child):
            errors.append(f"{child}: top-level skill entry cannot be a symlink")
            continue
        if not child.is_dir():
            errors.append(f"{child}: unexpected non-directory entry under skills root")
            continue
        skill_md = child / "SKILL.md"
        if os.path.islink(skill_md) or not skill_md.is_file():
            errors.append(f"{child}: missing regular SKILL.md entrypoint")
            continue
        skill_dirs.append(child)

    if not skill_dirs and not errors:
        errors.append(f"{resolved_root}: no skill entrypoints found")

    return skill_dirs, errors


def extract_quality_score(report: dict[str, Any]) -> tuple[float | None, str | None]:
    results = report.get("results")
    if not isinstance(results, list):
        return None, None
    for entry in results:
        if not isinstance(entry, dict) or entry.get("validator") != "QUALITY":
            continue
        quality = entry.get("quality")
        if not isinstance(quality, dict):
            return None, None
        raw_score = quality.get("overall_score")
        score = (
            float(raw_score)
            if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool)
            else None
        )
        grade = quality.get("grade")
        return score, grade if isinstance(grade, str) else None
    return None, None


def evaluate_skill_report(
    skill_name: str,
    returncode: int,
    report_path: Path,
    min_score: int,
    stderr: str,
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    if not report_path.is_file():
        detail = stderr.strip() or f"exit code {returncode}"
        return (
            {
                "name": skill_name,
                "passed": False,
                "returncode": returncode,
                "overall_status": "missing_report",
                "incomplete_scans": [],
                "total_errors": None,
                "total_warnings": None,
                "quality_score": None,
                "grade": None,
            },
            [f"{skill_name}: skillevaluator-tier1.json was not written ({detail})"],
        )

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (
            {
                "name": skill_name,
                "passed": False,
                "returncode": returncode,
                "overall_status": "invalid_report",
                "incomplete_scans": [],
                "total_errors": None,
                "total_warnings": None,
                "quality_score": None,
                "grade": None,
            },
            [f"{skill_name}: invalid skillevaluator-tier1.json ({exc})"],
        )

    if not isinstance(report, dict):
        return (
            {
                "name": skill_name,
                "passed": False,
                "returncode": returncode,
                "overall_status": "invalid_report",
                "incomplete_scans": [],
                "total_errors": None,
                "total_warnings": None,
                "quality_score": None,
                "grade": None,
            },
            [f"{skill_name}: skillevaluator-tier1.json root must be a JSON object"],
        )

    overall_passed = report.get("overall_passed")
    overall_status = report.get("overall_status")
    incomplete_scans = report.get("incomplete_scans")
    total_errors = report.get("total_errors")
    total_warnings = report.get("total_warnings")
    quality_score, grade = extract_quality_score(report)

    if returncode != 0:
        failures.append(f"{skill_name}: skillevaluator exited with code {returncode}")
    if overall_passed is not True or overall_status != "passed":
        failures.append(
            f"{skill_name}: tier1 status={overall_status!r} overall_passed={overall_passed!r}"
        )
    if not isinstance(incomplete_scans, list) or incomplete_scans:
        failures.append(
            f"{skill_name}: incomplete static scans reported: {incomplete_scans!r}"
        )
    if (
        not isinstance(total_errors, int)
        or isinstance(total_errors, bool)
        or total_errors != 0
    ):
        failures.append(f"{skill_name}: total_errors={total_errors!r}")
    if quality_score is None:
        failures.append(f"{skill_name}: missing Quality Score metadata in report")
    elif quality_score < min_score:
        failures.append(
            f"{skill_name}: quality score {quality_score:.1f} is below min_score {min_score}"
        )

    record = {
        "name": skill_name,
        "passed": not failures,
        "returncode": returncode,
        "overall_status": overall_status,
        "incomplete_scans": incomplete_scans if isinstance(incomplete_scans, list) else [],
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "quality_score": quality_score,
        "grade": grade,
    }
    return record, failures


def run_scan(
    skills_root: Path,
    *,
    baseline: Path | None,
    min_score: int,
    skillevaluator_bin: str,
    output_dir: Path | None,
) -> tuple[int, dict[str, Any], list[str]]:
    if not 0 <= min_score <= 100:
        return 1, {}, [f"min_score must be between 0 and 100 (got {min_score})"]

    resolved_bin = resolve_scanner_binary(skillevaluator_bin)
    if resolved_bin is None:
        return (
            1,
            {},
            [f"skillevaluator executable not found: {skillevaluator_bin!r}"],
        )

    resolved_baseline: Path | None = None
    if baseline is not None:
        if not baseline.is_file():
            return 1, {}, [f"{baseline}: SkillSpector baseline file does not exist"]
        resolved_baseline = baseline.resolve()

    skill_dirs, preflight_errors = validate_tree_hygiene(skills_root)
    if preflight_errors:
        return 1, {}, preflight_errors

    resolved_skills_root = skills_root.resolve()
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    records: list[dict[str, Any]] = []
    failures: list[str] = []

    def execute_into(base_out: Path) -> None:
        for skill_dir in skill_dirs:
            skill_out = base_out / skill_dir.name
            skill_out.mkdir(parents=True, exist_ok=True)
            cmd = [
                resolved_bin,
                "tier1",
                str(skill_dir),
                "--no-llm",
                "--min-score",
                str(min_score),
                "-r",
                "json",
                "-o",
                str(skill_out),
            ]
            if resolved_baseline is not None:
                cmd.extend(["--skillspector-baseline", str(resolved_baseline)])
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            record, skill_failures = evaluate_skill_report(
                skill_dir.name,
                proc.returncode,
                skill_out / "skillevaluator-tier1.json",
                min_score,
                proc.stderr,
            )
            records.append(record)
            failures.extend(skill_failures)

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        execute_into(output_dir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="secquoia-skill-scan-") as tmp:
            execute_into(Path(tmp))

    for offender in find_bytecode_artifacts(resolved_skills_root):
        failures.append(
            f"{offender}: Python bytecode was created during scanner execution"
        )

    summary = {
        "overall_passed": not failures,
        "skills_scanned": len(records),
        "min_score": min_score,
        "baseline": resolved_baseline.name if resolved_baseline is not None else None,
        "skills": records,
        "failures": failures,
    }
    if output_dir is not None:
        (output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
    return (0 if not failures else 1), summary, failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skills-root",
        type=Path,
        default=DEFAULT_SKILLS_ROOT,
        help="Root directory containing public skill folders (default: repo skills/).",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help="Evidence-bound SkillSpector v2 baseline YAML (default: .github/skillspector-baseline.yaml).",
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="Run without passing --skillspector-baseline.",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=70,
        help="Minimum passing SkillEvaluator Quality Score (default: 70).",
    )
    parser.add_argument(
        "--skillevaluator-bin",
        default="skillevaluator",
        help="Path or command name for skillevaluator (default: skillevaluator).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory to retain per-skill JSON reports and summary.json.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    baseline = None if args.no_baseline else args.baseline
    exit_code, summary, failures = run_scan(
        args.skills_root,
        baseline=baseline,
        min_score=args.min_score,
        skillevaluator_bin=args.skillevaluator_bin,
        output_dir=args.output_dir,
    )
    for record in summary.get("skills", []):
        score = record["quality_score"]
        score_text = f"{score:.1f}" if isinstance(score, float) else "n/a"
        grade_text = record["grade"] or "?"
        state = "PASS" if record["passed"] else "FAIL"
        print(
            f"[{state}] {record['name']}: score={score_text} ({grade_text}) "
            f"errors={record['total_errors']} warnings={record['total_warnings']}"
        )
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return exit_code
    print(
        f"All {summary['skills_scanned']} skills passed NVIDIA SkillEvaluator Tier 1 "
        f"(min_score={summary['min_score']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
