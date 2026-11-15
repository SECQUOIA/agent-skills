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
        self.baseline.write_text("version: 2\nscanner_version: '2.13.4'\nfingerprints: []\n", encoding="utf-8")
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

    def test_fails_closed_on_incomplete_scans_or_failed_gate_or_low_score(self) -> None:
        cases = [
            (
                "incomplete_scan",
                {
                    "overall_passed": True,
                    "overall_status": "passed",
                    "incomplete_scans": ["skillspector"],
                    "total_errors": 0,
                    "total_warnings": 0,
                    "results": [{"validator": "QUALITY", "quality": {"overall_score": 85.0, "grade": "B"}}],
                },
                0,
            ),
            (
                "failed_status",
                {
                    "overall_passed": False,
                    "overall_status": "failed",
                    "incomplete_scans": [],
                    "total_errors": 1,
                    "total_warnings": 0,
                    "results": [{"validator": "QUALITY", "quality": {"overall_score": 85.0, "grade": "B"}}],
                },
                1,
            ),
            (
                "low_score",
                {
                    "overall_passed": True,
                    "overall_status": "passed",
                    "incomplete_scans": [],
                    "total_errors": 0,
                    "total_warnings": 0,
                    "results": [{"validator": "QUALITY", "quality": {"overall_score": 65.0, "grade": "D"}}],
                },
                0,
            ),
        ]
        for label, payload, rc in cases:
            with self.subTest(case=label):
                fake_bin = self.make_fake_skillevaluator(
                    f"""
                    import json, pathlib, sys
                    args = sys.argv[1:]
                    out_dir = pathlib.Path(args[args.index("-o") + 1])
                    out_dir.mkdir(parents=True, exist_ok=True)
                    (out_dir / "skillevaluator-tier1.json").write_text(
                        json.dumps({payload!r}),
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

    def test_repository_merge_workflow_and_baseline_contracts(self) -> None:
        workflow_path = ROOT / ".github/workflows/skill-merge-scan.yml"
        self.assertTrue(workflow_path.is_file())
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        triggers = workflow.get("on") or workflow.get(True)
        self.assertIsInstance(triggers, dict)
        self.assertNotIn("pull_request", triggers)
        self.assertNotIn("pull_request_target", triggers)
        self.assertEqual(set(triggers.keys()), {"merge_group", "push", "workflow_dispatch"})
        self.assertEqual(triggers["push"].get("branches"), ["main"])

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
