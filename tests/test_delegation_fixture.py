"""Actual local Git/thread exercises, driven by scripts, not model trials."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("delegation_fixture", ROOT / "evals/delegation_fixture.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class DelegationFixtureTests(unittest.TestCase):
    def test_solo_and_concurrent_workers_produce_same_content_and_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            outcomes = []
            for parallel in (False, True):
                trial = fixture.Exercise(Path(directory) / str(parallel))
                changes = [{"left.txt": "left fixed\n"}, {"right.txt": "right fixed\n"}]
                if parallel:
                    assignments = [trial.assignment(name, patch) for name, patch in zip(("left", "right"), changes)]
                    results = trial.workers(assignments, parallel=True)
                    self.assertEqual(len({item["branch"] for item in results}), 2)
                    self.assertEqual(len({item["directory"] for item in results}), 2)
                    for result in results:
                        self.assertEqual(result["base"], trial.base)
                        self.assertEqual(result["source_tree"], fixture.revision(trial.repo, trial.base + "^{tree}"))
                        self.assertEqual(result["tree"], fixture.revision(Path(result["directory"]), "HEAD^{tree}"))
                    integrated = trial.integrate(results, current_source=trial.base)
                else:
                    integrated = trial.solo(changes)
                    self.assertEqual(fixture.git(trial.repo, "worktree", "list").stdout.count("\n"), 2)
                self.assertEqual(integrated["state"], "integrated")
                self.assertEqual((trial.integration / "left.txt").read_text(), "left fixed\n")
                self.assertEqual((trial.integration / "right.txt").read_text(), "right fixed\n")
                self.assertEqual(fixture.snapshot(trial.repo), trial.original)
                outcomes.append((integrated["state"], integrated["tree"]))
            self.assertEqual(outcomes[0], outcomes[1])

    def test_real_conflict_preserves_both_results_and_rolls_back_owned_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = fixture.Exercise(Path(directory) / "conflict")
            results = trial.workers([
                trial.assignment("a", {"left.txt": "choice A\n"}),
                trial.assignment("b", {"left.txt": "choice B\n"}),
            ], parallel=True)
            before = fixture.snapshot(trial.integration)
            original_workers = [fixture.snapshot(Path(item["directory"])) for item in results]
            result = trial.integrate(results, current_source=trial.base)
            self.assertEqual(result["state"], "conflict")
            self.assertIn("UU left.txt", result["status"])
            self.assertEqual(result["restored"], result["start"])
            self.assertEqual(fixture.snapshot(trial.integration), before)
            for item, snapshot in zip(results, original_workers):
                self.assertEqual(fixture.snapshot(Path(item["directory"])), snapshot)
                self.assertEqual(fixture.revision(trial.repo, item["branch"]), item["commit"])
            self.assertEqual(fixture.snapshot(trial.repo), trial.original)

    def test_changed_source_and_changed_handoff_are_quarantined_without_relabelling(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = fixture.Exercise(Path(directory) / "stale")
            assignment = trial.assignment("late", {"left.txt": "old-source result\n"})
            result = trial.work(assignment)
            (trial.integration / "left.txt").write_text("new upstream meaning\n")
            fixture.git(trial.integration, "add", "left.txt")
            fixture.git(trial.integration, "commit", "-m", "Upstream source changed")
            current_source = fixture.revision(trial.integration)
            before = fixture.snapshot(trial.integration)
            original_result = dict(result)
            self.assertEqual(trial.integrate([result], current_source)["state"], "quarantined")
            self.assertEqual(result, original_result)
            self.assertEqual(fixture.snapshot(trial.integration), before)
            (assignment["directory"] / "left.txt").write_text("late edit after handoff\n")
            self.assertEqual(trial.integrate([result], trial.base)["reason"], "worker changed after handoff")
            self.assertEqual(fixture.snapshot(trial.integration), before)
            self.assertEqual(fixture.snapshot(trial.repo), trial.original)

    def test_cancellation_receipt_does_not_end_active_writer_or_discard_partial_work(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = fixture.Exercise(Path(directory) / "interrupted")
            assignment = trial.assignment("worker", {"left.txt": "unfinished result\n"})
            completed_body = "outstanding write finished after cancellation\n"
            active, stopped = trial.interrupted_worker(assignment, {"left.txt": completed_body})
            self.assertTrue(active["cancellation_requested"])
            self.assertFalse(active["stopped"])
            self.assertTrue(active["directory_exists"])
            self.assertIn(" M left.txt", active["partial"]["status"])
            self.assertEqual(stopped["state"], "interrupted")
            self.assertNotEqual(stopped["partial"]["files"], active["partial"]["files"])
            self.assertEqual(stopped["partial"]["head"], active["partial"]["head"])
            self.assertEqual(trial.integrate([stopped])["state"], "quarantined")
            self.assertEqual((assignment["directory"] / "left.txt").read_text(), completed_body)
            self.assertEqual(fixture.revision(trial.repo, assignment["branch"]), trial.base)
            self.assertEqual(fixture.snapshot(trial.repo), trial.original)

    def test_component_success_does_not_establish_combined_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = fixture.Exercise(Path(directory) / "composition")
            results = trial.workers([
                trial.assignment("producer", {"producer.py": "def encode(n):\n    return {'length': n}\n"}),
                trial.assignment("consumer", {"consumer.py": "def decode(message):\n    return message['size']\n"}),
            ], parallel=True)
            commands = ["from producer import encode; assert encode(7) == {'length': 7}",
                        "from consumer import decode; assert decode({'size': 7}) == 7"]
            for result, command in zip(results, commands):
                checked = subprocess.run([sys.executable, "-B", "-c", command], cwd=result["directory"],
                                         capture_output=True, text=True, timeout=10)
                self.assertEqual(checked.returncode, 0, checked.stderr)
            integrated = trial.integrate(results, current_source=trial.base)
            self.assertEqual(integrated["state"], "integrated")
            command = "from producer import encode; from consumer import decode; assert decode(encode(7)) == 7"
            checked = subprocess.run([sys.executable, "-B", "-c", command], cwd=trial.integration,
                                     capture_output=True, text=True, timeout=10)
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("KeyError: 'size'", checked.stderr)
            self.assertEqual(integrated["tree"], fixture.revision(trial.integration, "HEAD^{tree}"))
            self.assertEqual(fixture.snapshot(trial.repo), trial.original)


if __name__ == "__main__":
    unittest.main()
