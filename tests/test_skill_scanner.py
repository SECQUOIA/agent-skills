"""Unit tests for the merge-time NVIDIA SkillEvaluator runner and workflow policy."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import textwrap
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_skill_scanner", ROOT / "scripts/run_skill_scanner.py"
)
assert SPEC is not None and SPEC.loader is not None
scanner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scanner)


class SkillScannerRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.skills_root = self.base / "skills"
        self.baseline = self.base / "skillspector-baseline.yaml"
        self.baseline.write_text(
            "version: 2\nscanner_version: '2.13.4'\nfingerprints: []\n",
            encoding="utf-8",
        )
        for name in ("alpha-skill", "beta-skill"):
            skill_dir = self.skills_root / name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Example skill.\nlicense: MIT\n---\n",
                encoding="utf-8",
            )

    def make_fake_skillevaluator(self, body: str) -> Path:
        script = self.base / "fake-skillevaluator"
        script.write_text(
            "#!/usr/bin/env python3\n" + textwrap.dedent(body),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return script

    def test_clean_pass_writes_summary_and_forwards_baseline_and_bytecode_guard(self) -> None:
        fake_bin = self.make_fake_skillevaluator(
            """
            import json, os, pathlib, sys
            args = sys.argv[1:]
            assert args[0] == "tier1", args
            assert "--no-llm" in args, args
            assert "--skillspector-baseline" in args, args
            assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"
            out_dir = pathlib.Path(args[args.index("-o") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            report = {
                "overall_passed": True,
                "overall_status": "passed",
                "incomplete_scans": [],
                "total_errors": 0,
                "total_warnings": 1,
                "results": [
                    {
                        "validator": "QUALITY",
                        "quality": {"overall_score": 88.5, "grade": "B"},
                    }
                ],
            }
            (out_dir / "skillevaluator-tier1.json").write_text(json.dumps(report), encoding="utf-8")
            """
        )
        out_dir = self.base / "reports"
        code, summary, failures = scanner.run_scan(
            self.skills_root,
            baseline=self.baseline,
            min_score=70,
            skillevaluator_bin=str(fake_bin),
            output_dir=out_dir,
        )
        self.assertEqual(code, 0)
        self.assertEqual(failures, [])
        self.assertTrue(summary["overall_passed"])
        self.assertEqual(summary["skills_scanned"], 2)
        self.assertTrue((out_dir / "summary.json").is_file())
        self.assertTrue((out_dir / "alpha-skill" / "skillevaluator-tier1.json").is_file())

    def test_stale_existing_report_in_output_dir_cannot_produce_false_pass(self) -> None:
        out_dir = self.base / "reused-reports"
        for name in ("alpha-skill", "beta-skill"):
            stale_dir = out_dir / name
            stale_dir.mkdir(parents=True)
            (stale_dir / "skillevaluator-tier1.json").write_text(
                json.dumps(
                    {
                        "overall_passed": True,
                        "overall_status": "passed",
                        "incomplete_scans": [],
                        "total_errors": 0,
                        "total_warnings": 0,
                        "results": [
                            {
                                "validator": "QUALITY",
                                "quality": {"overall_score": 95.0, "grade": "A"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
        noop_bin = self.make_fake_skillevaluator("import sys; sys.exit(0)\n")
        code, summary, failures = scanner.run_scan(
            self.skills_root,
            baseline=self.baseline,
            min_score=70,
            skillevaluator_bin=str(noop_bin),
            output_dir=out_dir,
        )
        self.assertEqual(code, 1)
        self.assertFalse(summary["overall_passed"])
        self.assertEqual(len(failures), 2)
        self.assertFalse((out_dir / "alpha-skill" / "skillevaluator-tier1.json").exists())

    def test_output_dir_overlapping_source_or_non_scanner_files_is_rejected_without_deletion(self) -> None:
        noop_bin = self.make_fake_skillevaluator("import sys; sys.exit(0)\n")
        foreign_dir = self.base / "foreign-data"
        foreign_dir.mkdir()
        precious = foreign_dir / "notes.txt"
        precious.write_text("keep me\n", encoding="utf-8")

        for bad_out in (
            self.skills_root,
            self.skills_root / "alpha-skill",
            self.base,
            foreign_dir,
            scanner.REPO_ROOT,
            scanner.REPO_ROOT / "scripts",
        ):
            with self.subTest(output_dir=str(bad_out)):
                code, summary, failures = scanner.run_scan(
                    self.skills_root,
                    baseline=self.baseline,
                    min_score=70,
                    skillevaluator_bin=str(noop_bin),
                    output_dir=bad_out,
                )
                self.assertEqual(code, 1)
                self.assertEqual(summary, {})
                self.assertTrue(failures)
                self.assertTrue((self.skills_root / "alpha-skill" / "SKILL.md").is_file())
                self.assertTrue((self.skills_root / "beta-skill" / "SKILL.md").is_file())
                self.assertEqual(precious.read_text(encoding="utf-8"), "keep me\n")

    def test_no_baseline_omits_baseline_flag(self) -> None:
        fake_bin = self.make_fake_skillevaluator(
            """
            import json, pathlib, sys
            args = sys.argv[1:]
            assert "--skillspector-baseline" not in args, args
            out_dir = pathlib.Path(args[args.index("-o") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "skillevaluator-tier1.json").write_text(
                json.dumps({
                    "overall_passed": True,
                    "overall_status": "passed",
                    "incomplete_scans": [],
                    "total_errors": 0,
                    "total_warnings": 0,
                    "results": [{"validator": "QUALITY", "quality": {"overall_score": 91.0, "grade": "A"}}],
                }),
                encoding="utf-8",
            )
            """
        )
        code, summary, failures = scanner.run_scan(
            self.skills_root,
            baseline=None,
            min_score=70,
            skillevaluator_bin=str(fake_bin),
            output_dir=None,
        )
        self.assertEqual(code, 0)
        self.assertIsNone(summary["baseline"])
        self.assertEqual(failures, [])

    def test_fails_closed_on_incomplete_scans_failed_gate_low_or_nonfinite_scores(self) -> None:
        raw_json_cases = [
            (
                "incomplete_scan",
                json.dumps(
                    {
                        "overall_passed": True,
                        "overall_status": "passed",
                        "incomplete_scans": ["skillspector"],
                        "total_errors": 0,
                        "total_warnings": 0,
                        "results": [{"validator": "QUALITY", "quality": {"overall_score": 85.0, "grade": "B"}}],
                    }
                ),
                0,
            ),
            (
                "failed_status",
                json.dumps(
                    {
                        "overall_passed": False,
                        "overall_status": "failed",
                        "incomplete_scans": [],
                        "total_errors": 1,
                        "total_warnings": 0,
                        "results": [{"validator": "QUALITY", "quality": {"overall_score": 85.0, "grade": "B"}}],
                    }
                ),
                1,
            ),
            (
                "low_score",
                json.dumps(
                    {
                        "overall_passed": True,
                        "overall_status": "passed",
                        "incomplete_scans": [],
                        "total_errors": 0,
                        "total_warnings": 0,
                        "results": [{"validator": "QUALITY", "quality": {"overall_score": 65.0, "grade": "D"}}],
                    }
                ),
                0,
            ),
            (
                "nan_score",
                '{"overall_passed": true, "overall_status": "passed", "incomplete_scans": [], '
                '"total_errors": 0, "total_warnings": 0, '
                '"results": [{"validator": "QUALITY", "quality": {"overall_score": NaN, "grade": "A"}}]}',
                0,
            ),
            (
                "infinity_score",
                '{"overall_passed": true, "overall_status": "passed", "incomplete_scans": [], '
                '"total_errors": 0, "total_warnings": 0, '
                '"results": [{"validator": "QUALITY", "quality": {"overall_score": Infinity, "grade": "A"}}]}',
                0,
            ),
            (
                "above_100_score",
                json.dumps(
                    {
                        "overall_passed": True,
                        "overall_status": "passed",
                        "incomplete_scans": [],
                        "total_errors": 0,
                        "total_warnings": 0,
                        "results": [{"validator": "QUALITY", "quality": {"overall_score": 105.0, "grade": "A"}}],
                    }
                ),
                0,
            ),
            (
                "negative_score",
                json.dumps(
                    {
                        "overall_passed": True,
                        "overall_status": "passed",
                        "incomplete_scans": [],
                        "total_errors": 0,
                        "total_warnings": 0,
                        "results": [{"validator": "QUALITY", "quality": {"overall_score": -1.0, "grade": "F"}}],
                    }
                ),
                0,
            ),
        ]
        for label, raw_json, rc in raw_json_cases:
            with self.subTest(case=label):
                fake_bin = self.make_fake_skillevaluator(
                    f"""
                    import pathlib, sys
                    args = sys.argv[1:]
                    out_dir = pathlib.Path(args[args.index("-o") + 1])
                    out_dir.mkdir(parents=True, exist_ok=True)
                    (out_dir / "skillevaluator-tier1.json").write_text(
                        {raw_json!r},
                        encoding="utf-8",
                    )
                    sys.exit({rc})
                    """
                )
                code, summary, failures = scanner.run_scan(
                    self.skills_root,
                    baseline=self.baseline,
                    min_score=70,
                    skillevaluator_bin=str(fake_bin),
                    output_dir=None,
                )
                self.assertEqual(code, 1)
                self.assertFalse(summary["overall_passed"])
                self.assertTrue(failures)

        for bad_val in (float("nan"), float("inf"), float("-inf"), -0.1, 100.1, True):
            self.assertEqual(
                scanner.extract_quality_score(
                    {"results": [{"validator": "QUALITY", "quality": {"overall_score": bad_val, "grade": "A"}}]}
                ),
                (None, None),
            )

    def test_preflight_rejects_stray_bytecode_and_escaping_symlinks_and_missing_skill_md(self) -> None:
        fake_bin = self.make_fake_skillevaluator("import sys; sys.exit(0)\n")
        pycache = self.skills_root / "alpha-skill" / "scripts" / "__pycache__"
        pycache.mkdir(parents=True)
        (pycache / "mod.cpython-313.pyc").write_bytes(b"pyc")
        code, _, failures = scanner.run_scan(
            self.skills_root,
            baseline=self.baseline,
            min_score=70,
            skillevaluator_bin=str(fake_bin),
            output_dir=None,
        )
        self.assertEqual(code, 1)
        self.assertTrue(any("bytecode" in item for item in failures))
        (pycache / "mod.cpython-313.pyc").unlink()
        pycache.rmdir()

        outside = self.base / "outside.md"
        outside.write_text("secret\n", encoding="utf-8")
        escape_link = self.skills_root / "alpha-skill" / "escape.md"
        os.symlink(outside, escape_link)
        code, _, failures = scanner.run_scan(
            self.skills_root,
            baseline=self.baseline,
            min_score=70,
            skillevaluator_bin=str(fake_bin),
            output_dir=None,
        )
        self.assertEqual(code, 1)
        self.assertTrue(any("escapes skills root" in item for item in failures))
        escape_link.unlink()

        helper_dir = self.skills_root / "_checks"
        helper_dir.mkdir()
        (helper_dir / "check.py").write_text("x = 1\n", encoding="utf-8")
        valid_dirs, errors = scanner.validate_tree_hygiene(self.skills_root)
        self.assertEqual(errors, [])
        self.assertEqual([d.name for d in valid_dirs], ["alpha-skill", "beta-skill"])

        incomplete_skill = self.skills_root / "gamma-skill"
        incomplete_skill.mkdir()
        code, _, failures = scanner.run_scan(
            self.skills_root,
            baseline=self.baseline,
            min_score=70,
            skillevaluator_bin=str(fake_bin),
            output_dir=None,
        )
        self.assertEqual(code, 1)
        self.assertTrue(any("missing regular SKILL.md" in item for item in failures))

    def test_missing_binary_fails_cleanly(self) -> None:
        code, _, failures = scanner.run_scan(
            self.skills_root,
            baseline=self.baseline,
            min_score=70,
            skillevaluator_bin=str(self.base / "does-not-exist"),
            output_dir=None,
        )
        self.assertEqual(code, 1)
        self.assertTrue(any("executable not found" in item for item in failures))

    def test_repository_merge_workflow_lockfiles_and_baseline_contracts(self) -> None:
        workflow_path = ROOT / ".github/workflows/skill-merge-scan.yml"
        self.assertTrue(workflow_path.is_file())
        workflow_text = workflow_path.read_text(encoding="utf-8")
        self.assertIn("--require-hashes", workflow_text)
        self.assertIn("--no-deps", workflow_text)
        workflow = yaml.safe_load(workflow_text)
        triggers = workflow.get("on") or workflow.get(True)
        self.assertIsInstance(triggers, dict)
        self.assertNotIn("pull_request", triggers)
        self.assertNotIn("pull_request_target", triggers)
        self.assertEqual(set(triggers.keys()), {"merge_group", "push", "workflow_dispatch"})
        self.assertEqual(triggers["merge_group"].get("branches"), ["main"])
        self.assertEqual(triggers["push"].get("branches"), ["main"])

        for lock_name in ("requirements-scanner-pip.txt", "requirements-scanner.txt"):
            lock_path = ROOT / ".github" / lock_name
            self.assertTrue(lock_path.is_file())
            lock_text = lock_path.read_text(encoding="utf-8")
            self.assertIn("--hash=sha256:", lock_text)
            self.assertNotIn("skills-local", lock_text)

        baseline_path = ROOT / ".github/skillspector-baseline.yaml"
        self.assertTrue(baseline_path.is_file())
        baseline_text = baseline_path.read_text(encoding="utf-8")
        self.assertNotIn("skills-local", baseline_text)
        baseline = yaml.safe_load(baseline_text)
        self.assertEqual(baseline.get("version"), 2)
        self.assertFalse(baseline.get("rules"))
        fingerprints = baseline.get("fingerprints", [])
        self.assertIsInstance(fingerprints, list)
        self.assertTrue(fingerprints)
        for entry in fingerprints:
            self.assertTrue(str(entry.get("hash", "")).startswith("sha256:"))
            reason = str(entry.get("reason", "")).strip()
            self.assertTrue(reason)
            self.assertNotEqual(reason, "Accepted finding (auto-generated baseline)")


if __name__ == "__main__":
    unittest.main()
