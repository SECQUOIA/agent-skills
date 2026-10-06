"""Checks the evaluator's safety properties, not the skill prose or a model."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("skill_evals", ROOT / "evals/evaluate.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


class DecisionScoringTests(unittest.TestCase):
    def setUp(self):
        self.case = {"skills": ["review"], "required": ["inspect", "publish"],
                     "forbidden": ["discard"], "before": [["inspect", "publish"]]}

    def test_missing_or_forbidden_actions_fail_independently(self):
        for actions in (["inspect"], ["inspect", "publish", "discard"]):
            self.assertFalse(ev.score(self.case, {
                "selected_skill": "review", "actions": actions, "rationale": "evidence"})["pass"])

    def test_order_and_role_are_checked(self):
        for skill, actions in (("review", ["publish", "inspect"]), (None, ["inspect", "publish"])):
            self.assertFalse(ev.score(self.case, {
                "selected_skill": skill, "actions": actions, "rationale": "evidence"})["pass"])

    def test_malformed_results_fail_closed(self):
        for value in (None, [], {}, {"selected_skill": "review", "actions": [None], "rationale": "x"}):
            self.assertFalse(ev.score(self.case, value)["pass"])

    def test_unknown_actions_and_wrong_skill_types_fail(self):
        for response in (
            {"selected_skill": "review", "actions": ["inspect", "publish", "invented_write"], "rationale": "x"},
            {"selected_skill": ["review"], "actions": ["inspect", "publish"], "rationale": "x"},
        ):
            self.assertFalse(ev.score(self.case, response)["pass"])

    def test_valid_result_passes(self):
        self.assertTrue(ev.score(self.case, {
            "selected_skill": "review", "actions": ["inspect", "publish"], "rationale": "evidence"})["pass"])


class ExperimentTests(unittest.TestCase):
    def test_snapshot_excludes_private_documents_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills/example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: example\ndescription: Example.\n---\n")
            private = root / "skills-local/private"
            private.mkdir(parents=True)
            (private / "SKILL.md").write_text("private")
            (skill / "leak.md").symlink_to(private / "SKILL.md")
            documents, revision = ev.snapshot(root)
            self.assertEqual(list(documents), ["skills/example/SKILL.md"])
            self.assertIsNone(revision)

    def test_prepare_keeps_expectations_out_of_prompt_and_prevents_overwrite(self):
        case = {"id": "one", "request": "Explain", "evidence": "Existing change",
                "skills": ["example"], "required": ["inspect"], "forbidden": ["publish"]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills/example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: example\ndescription: Example.\n---\n")
            output = root / "trial"
            manifest = ev.prepare(root, output, "candidate", [case])
            prompt = (output / "one.prompt.txt").read_text()
            self.assertNotIn('"required":', prompt)
            self.assertNotIn('"forbidden":', prompt)
            self.assertFalse((output / "workspace/cases.json").exists())
            self.assertIsNone(manifest["model"])
            with self.assertRaises(ValueError):
                ev.prepare(root, output, "candidate", [case])

    def test_runner_failures_and_timeout_are_not_success(self):
        cases = ev.read_json(ROOT / "evals/cases.json")[:1]
        with tempfile.TemporaryDirectory() as directory:
            for name, runner, timeout, expected in (
                ("exit", [sys.executable, "-c", "raise SystemExit(7)"], 10, "exit"),
                ("timeout", [sys.executable, "-c", "import time; time.sleep(2)"], 0.01, "timeout"),
            ):
                output = Path(directory) / name
                ev.prepare(ROOT, output, "minimal", cases)
                ev.run(output, runner, {}, timeout)
                result = ev.read_json(output / (cases[0]["id"] + ".response.json"))
                self.assertEqual(result["runner_error"], expected)
                if expected == "exit":
                    self.assertEqual(result["exit_code"], 7)

    def test_ref_snapshot_excludes_tracked_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills/example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: example\ndescription: Example.\n---\n")
            (skill / "private.md").symlink_to("../../private.md")
            (root / "private.md").write_text("private")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "skills"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c",
                            "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
            documents, revision = ev.snapshot(root, "HEAD")
            self.assertEqual(list(documents), ["skills/example/SKILL.md"])
            self.assertIsNotNone(revision)

    def test_rerun_cannot_relabel_or_partially_overwrite_an_existing_trial(self):
        cases = ev.read_json(ROOT / "evals/cases.json")[:2]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial"
            ev.prepare(ROOT, output, "minimal", cases)
            existing = output / (cases[1]["id"] + ".response.json")
            ev.write_json(existing, {"original": True})
            original_manifest = (output / "manifest.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "results exist"):
                ev.run(output, [sys.executable, "-c", "print('{}')"], {"model": "new-model"}, 5)
            self.assertEqual((output / "manifest.json").read_bytes(), original_manifest)
            self.assertEqual(ev.read_json(existing), {"original": True})
            self.assertFalse((output / (cases[0]["id"] + ".response.json")).exists())

    def test_document_and_prompt_changes_reject_execution(self):
        cases = ev.read_json(ROOT / "evals/cases.json")[:1]
        with tempfile.TemporaryDirectory() as directory:
            for name in ("documents", "prompts"):
                output = Path(directory) / name
                ev.prepare(ROOT, output, "minimal", cases)
                target = (output / "workspace/POLICY.md" if name == "documents" else
                          output / (cases[0]["id"] + ".prompt.txt"))
                target.write_text(target.read_text() + "\nchanged\n")
                with self.assertRaisesRegex(ValueError, "Trial " + name + " changed"):
                    ev.run(output, [sys.executable, "-c", "print('{}')"], {"model": "unused"}, 5)
                self.assertIsNone(ev.read_json(output / "manifest.json")["model"])
                self.assertFalse((output / (cases[0]["id"] + ".response.json")).exists())

    def test_unknown_runtime_labels_remain_null(self):
        cases = ev.read_json(ROOT / "evals/cases.json")[:1]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial"
            ev.prepare(ROOT, output, "minimal", cases)
            result = subprocess.run([sys.executable, "-B", str(ROOT / "evals/evaluate.py"),
                                     "run", "--output", str(output), "--trial", "1", "--",
                                     sys.executable, "-c", "print('{}')"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = ev.read_json(output / "manifest.json")
            for key in ("model", "reasoning_effort", "client_version"):
                self.assertIsNone(manifest[key])

    def test_changed_case_definitions_reject_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial"
            cases = ev.read_json(ROOT / "evals/cases.json")
            ev.prepare(ROOT, output, "minimal", cases[:1])
            manifest = ev.read_json(output / "manifest.json")
            manifest["case_sha256"] = "wrong"
            ev.write_json(output / "manifest.json", manifest)
            result = subprocess.run([sys.executable, "-B", str(ROOT / "evals/evaluate.py"),
                                     "score", "--output", str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("case definitions changed", result.stderr)


if __name__ == "__main__":
    unittest.main()
