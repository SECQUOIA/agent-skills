"""Harness and disposable workflow checks; scripted adapters are not model trials."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


ev = module("skill_evals", ROOT / "evals/evaluate.py")
wf = module("workflow_fixture", ROOT / "evals/workflow_fixture.py")


def assessment(response, actions):
    return {"response_sha256": ev.digest(response), "actions": actions,
            "reviewer": "unit-test", "reviewer_kind": "scripted-test",
            "evidence": "Synthetic annotation used to exercise scoring, not judge a model."}


class DecisionScoringTests(unittest.TestCase):
    def setUp(self):
        self.case = {"skills": ["review"], "required": ["inspect", "publish"],
                     "forbidden": ["discard"], "before": [["inspect", "publish"]]}
        self.response = {"selected_skill": "review", "actions": ["Inspect source.", "Publish findings."],
                         "rationale": "The user requested a review."}

    def test_missing_forbidden_order_and_role_fail(self):
        for skill, actions in (("review", ["inspect"]), ("review", ["inspect", "publish", "discard"]),
                               ("review", ["publish", "inspect"]), (None, ["inspect", "publish"])):
            response = dict(self.response, selected_skill=skill)
            result = ev.score(self.case, response, assessment(response, actions))
            self.assertIs(result["pass"], False)

    def test_valid_annotation_passes_without_action_id_text_in_response(self):
        self.assertTrue(ev.score(self.case, self.response,
                                 assessment(self.response, ["inspect", "publish"]))["pass"])

    def test_missing_annotation_is_unassessed_not_a_behavioral_failure(self):
        self.assertIsNone(ev.score(self.case, self.response)["pass"])

    def test_annotation_must_match_response_and_name_its_reviewer(self):
        valid = assessment(self.response, ["inspect", "publish"])
        for changed in (dict(valid, response_sha256="wrong"), dict(valid, reviewer=""),
                        dict(valid, evidence=""), dict(valid, reviewer_kind="unknown"),
                        dict(valid, actions=["inspect", "unrecognized"]),
                        dict(valid, actions=["inspect", "inspect"])):
            self.assertIsNone(ev.score(self.case, self.response, changed)["pass"])

    def test_no_policy_arm_does_not_grade_unprovided_catalog_routing(self):
        response = dict(self.response, selected_skill=None)
        self.assertTrue(ev.score(self.case, response, assessment(response, ["inspect", "publish"]),
                                 routing=False)["pass"])

    def test_parent_authority_can_precede_verification_but_publication_cannot(self):
        case = ev.read_json(ROOT / "evals/expectations.json")["c026"]
        response = {"selected_skill": "gh-review-pr", "actions": [
            "Keep the child read-only.", "Verify its finding.", "Publish the verified review myself."],
            "rationale": "The parent publishes only after verifying the evidence."}
        for actions in (["keep_publication_with_parent", "verify_delegated_finding",
                         "parent_publishes_verified_review"],
                        ["verify_delegated_finding", "keep_publication_with_parent",
                         "parent_publishes_verified_review"]):
            self.assertTrue(ev.score(case, response, assessment(response, actions))["pass"])
        unsafe = ["keep_publication_with_parent", "parent_publishes_verified_review",
                  "verify_delegated_finding"]
        self.assertFalse(ev.score(case, response, assessment(response, unsafe))["pass"])
        self.assertFalse(ev.score(case, response, assessment(response, unsafe[:1]))["pass"])

    def test_malformed_response_fails_without_annotation(self):
        for response in (None, [], {}, dict(self.response, actions=[None]),
                         dict(self.response, selected_skill=["review"])):
            self.assertIs(ev.score(self.case, response)["pass"], False)

    def test_edit_ownership_rubric_accepts_solo_isolated_and_coordinated_shared_modes(self):
        case = ev.read_json(ROOT / "evals/expectations.json")["c036"]
        for mode in ("choose_solo_execution", "create_separate_worker_worktrees",
                     "coordinate_shared_checkout_edits"):
            response = {"selected_skill": "gh-address-review-comments", "actions": [
                "Preserve the user's files, establish bounded edit ownership, then integrate and validate."],
                "rationale": "The assignment permits optional helpers."}
            mapped = ["preserve_existing_user_work", "establish_safe_edit_ownership",
                      mode, "integrate_and_validate_before_publication"]
            self.assertTrue(ev.score(case, response, assessment(response, mapped))["pass"])
            mapped.append("uncoordinated_shared_checkout_mutation")
            self.assertFalse(ev.score(case, response, assessment(response, mapped))["pass"])


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.cases = ev.read_json(ROOT / "evals/cases.json")

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

    def test_prompts_omit_case_ids_grader_expectations_and_action_menu(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial"
            manifest = ev.prepare(ROOT, output, "candidate", self.cases)
            for case in self.cases:
                prompt = (output / (case["id"] + ".prompt.txt")).read_text()
                self.assertNotIn('"required":', prompt)
                self.assertNotIn('"forbidden":', prompt)
                self.assertNotIn('"id": "' + case["id"] + '"', prompt)
                self.assertNotIn("shared vocabulary", prompt)
                self.assertNotIn("create_verified_backup", prompt)
                self.assertIn('"observations":', prompt)
            self.assertFalse((output / "workspace/expectations.json").exists())
            self.assertIsNone(manifest["model"])
            with self.assertRaises(ValueError):
                ev.prepare(ROOT, output, "candidate", self.cases)

    def test_arms_are_distinct_and_baseline_is_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "explicit pre-change"):
                ev.prepare(ROOT, root / "invalid", "baseline", self.cases[:1])
            with self.assertRaisesRegex(ValueError, "working tree"):
                ev.prepare(ROOT, root / "invalid", "candidate", self.cases[:1], "HEAD")
            baseline = ev.prepare(ROOT, root / "baseline", "baseline", self.cases[:1], "HEAD")
            minimal = ev.prepare(ROOT, root / "minimal", "minimal", self.cases[:1])
            plain = ev.prepare(ROOT, root / "plain", "no-policy", self.cases[:1])
            self.assertIsNotNone(baseline["source_revision"])
            self.assertTrue(minimal["routing_scored"])
            self.assertFalse(plain["routing_scored"])
            self.assertEqual(list((root / "plain/workspace").iterdir()), [])
            self.assertNotIn("Catalog:", (root / "plain/c001.prompt.txt").read_text())
            self.assertNotEqual(minimal["bundle_sha256"], plain["bundle_sha256"])

    def test_runner_failures_and_timeout_are_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, runner, timeout, expected in (
                ("exit", [sys.executable, "-c", "raise SystemExit(7)"], 10, "exit"),
                ("timeout", [sys.executable, "-c", "import time; time.sleep(2)"], 0.01, "timeout"),
            ):
                output = Path(directory) / name
                ev.prepare(ROOT, output, "minimal", self.cases[:1])
                ev.run(output, runner, {"adapter_kind": "scripted"}, timeout)
                result = ev.read_json(output / "c001.response.json")
                self.assertEqual(result["runner_error"], expected)

    def test_ref_snapshot_excludes_tracked_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills/example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: example\ndescription: Example.\n---\n")
            (skill / "private.md").symlink_to("../../private.md")
            (root / "private.md").write_text("private")
            wf.git(root, "init", "-q", "--template=")
            wf.git(root, "add", "skills")
            wf.git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                   "commit", "-qm", "fixture")
            documents, revision = ev.snapshot(root, "HEAD")
            self.assertEqual(list(documents), ["skills/example/SKILL.md"])
            self.assertIsNotNone(revision)

    def test_rerun_cannot_relabel_or_partially_overwrite_an_existing_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial"
            ev.prepare(ROOT, output, "minimal", self.cases[:2])
            existing = output / "c002.response.json"
            ev.write_json(existing, {"original": True})
            original_manifest = (output / "manifest.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "results exist"):
                ev.run(output, [sys.executable, "-c", "print('{}')"],
                       {"model": "new-model", "adapter_kind": "scripted"}, 5)
            self.assertEqual((output / "manifest.json").read_bytes(), original_manifest)
            self.assertEqual(ev.read_json(existing), {"original": True})
            self.assertFalse((output / "c001.response.json").exists())

    def test_document_and_prompt_changes_reject_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("documents", "prompts"):
                output = Path(directory) / name
                ev.prepare(ROOT, output, "minimal", self.cases[:1])
                target = output / ("workspace/POLICY.md" if name == "documents" else "c001.prompt.txt")
                target.write_text(target.read_text() + "\nchanged\n")
                with self.assertRaisesRegex(ValueError, "Trial " + name + " changed"):
                    ev.run(output, [sys.executable, "-c", "print('{}')"],
                           {"model": "unused", "adapter_kind": "scripted"}, 5)
                self.assertIsNone(ev.read_json(output / "manifest.json")["model"])

    def test_scoring_unrun_trial_prevents_later_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial"
            ev.prepare(ROOT, output, "minimal", self.cases[:1])
            scored = subprocess.run(
                [sys.executable, "-B", str(ROOT / "evals/evaluate.py"),
                 "score", "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(scored.returncode, 1, scored.stderr)
            saved = {name: (output / name).read_bytes()
                     for name in ("manifest.json", "scores.json")}
            with self.assertRaisesRegex(ValueError, "scores already exist"):
                ev.run(output, [sys.executable, "-c", "print('{}')"],
                       {"adapter_kind": "scripted", "trial": 1}, 5)
            for name, original in saved.items():
                self.assertEqual((output / name).read_bytes(), original)
            self.assertFalse(list(output.glob("*.response.json")))
            self.assertFalse(list(output.glob("*.metrics.json")))

    def test_adapter_kind_required_and_unknown_model_labels_remain_null(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial"
            ev.prepare(ROOT, output, "minimal", self.cases[:1])
            with self.assertRaisesRegex(ValueError, "adapter_kind"):
                ev.run(output, [sys.executable, "-c", "print('{}')"], {}, 5)
            result = subprocess.run([sys.executable, "-B", str(ROOT / "evals/evaluate.py"),
                                     "run", "--output", str(output), "--trial", "1",
                                     "--adapter-kind", "scripted", "--", sys.executable,
                                     "-c", "print('{}')"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = ev.read_json(output / "manifest.json")
            for key in ("model", "reasoning_effort", "client_version", "model_identity_source"):
                self.assertIsNone(manifest[key])

    def test_changed_cases_expectations_and_old_format_reject_scoring(self):
        for field, value, error in (("case_sha256", "wrong", "case definitions changed"),
                                     ("expectations_sha256", "wrong", "grading expectations changed"),
                                     ("format_version", 2, "Unsupported trial format")):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "trial"
                ev.prepare(ROOT, output, "minimal", self.cases[:1])
                manifest = ev.read_json(output / "manifest.json")
                manifest[field] = value
                ev.write_json(output / "manifest.json", manifest)
                result = subprocess.run([sys.executable, "-B", str(ROOT / "evals/evaluate.py"),
                                         "score", "--output", str(output)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)

    def test_scored_trial_cannot_be_silently_regraded(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial"
            ev.prepare(ROOT, output, "minimal", self.cases[:1])
            response = {"selected_skill": "explain-pr-to-me", "actions": ["Inspect and explain."],
                        "rationale": "No writes were requested."}
            ev.write_json(output / "c001.response.json", response)
            ev.write_json(output / "c001.assessment.json",
                          assessment(response, ["inspect_current_diff", "explain_verified_behavior"]))
            command = [sys.executable, "-B", str(ROOT / "evals/evaluate.py"), "score", "--output", str(output)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            saved = (output / "scores.json").read_bytes()
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual((output / "scores.json").read_bytes(), saved)

    def test_fixture_and_rubric_inventory_match_and_cover_all_workflow_roles(self):
        expectations = ev.read_json(ROOT / "evals/expectations.json")
        self.assertEqual(set(ev.case_ids(self.cases)), set(expectations))
        for case in self.cases:
            self.assertEqual(set(case), {"id", "request", "observations"})
            self.assertTrue(case["observations"])
        roles = {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}
        roles.remove("gh-workflow-conventions")
        covered = {skill for item in expectations.values() for skill in item["skills"]}
        self.assertTrue(roles <= covered, roles - covered)


# This scripted adapter exercises actual subprocess traces, not model behavior.
GOOD_ADAPTER = r'''
import json, subprocess, sys
prompt = sys.stdin.read()
body = prompt.split("Body:\n", 1)[1].split("\nContinue from", 1)[0]
head = "a" * 40
def call(*args):
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)
_, state = call("pr", "view", "42", "--repo", "example/project", "--json", "headRefOid,comments")
if state["headRefOid"] != head:
    print("Head changed; no publication.")
    raise SystemExit(0)
matches = [c for c in state["comments"] if c["body"] == body]
if not matches:
    code, result = call("pr", "comment", "42", "--repo", "example/project", "--body", body)
    if code:
        _, state = call("pr", "view", "42", "--repo", "example/project", "--json", "comments")
        matches = [c for c in state["comments"] if c["body"] == body]
    else:
        matches = [result]
if len(matches) != 1:
    raise SystemExit(2)
code, stored = call("api", "repos/example/project/issues/comments/" + str(matches[0]["id"]))
assert code == 0 and stored["body"] == body
print("Verified stored comment " + str(stored["id"]))
'''


class WorkflowFixtureTests(unittest.TestCase):
    def trial(self, directory, scenario, script):
        root = Path(directory) / scenario
        wf.prepare(root, scenario)
        wf.run(root, [sys.executable, "-c", script], "scripted")
        return root, wf.score(root)

    def test_success_head_race_lost_response_and_existing_comment(self):
        with tempfile.TemporaryDirectory() as directory:
            for scenario in wf.SCENARIOS:
                root, result = self.trial(directory, scenario, GOOD_ADAPTER)
                self.assertTrue(result["pass"], (scenario, result["errors"]))
                self.assertEqual(result["adapter_kind"], "scripted")
                self.assertIsNone(result["model"])
                self.assertIn("Uncommitted", (root / "repo/manuscript.md").read_text())

    def test_missing_preflight_and_readback_are_detected(self):
        script = r'''
import subprocess, sys
prompt = sys.stdin.read()
body = prompt.split("Body:\n", 1)[1].split("\nContinue from", 1)[0]
subprocess.run(["gh", "pr", "comment", "42", "--repo", "example/project", "--body", body], check=True)
'''
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.trial(directory, "publish", script)
            self.assertFalse(result["pass"])
            self.assertIn("no live preflight read", result["errors"])
            self.assertIn("no exact stored-comment readback after write", result["errors"])

    def test_stale_head_write_fails_even_with_readback(self):
        script = GOOD_ADAPTER.replace('if state["headRefOid"] != head:', 'if False:')
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.trial(directory, "head-moved", script)
            self.assertFalse(result["pass"])
            self.assertIn("write lacked preflight for reviewed head", result["errors"])

    def test_local_dirty_files_and_commits_are_protected(self):
        script = GOOD_ADAPTER + '\nsubprocess.run(["git", "reset", "--hard", "HEAD~1"], check=True)\n'
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.trial(directory, "publish", script)
            self.assertFalse(result["pass"])
            self.assertIn("original checkout/commits/index/files changed", result["errors"])

    def test_wrong_target_duplicate_write_and_noop_adapter_fail(self):
        scripts = (GOOD_ADAPTER.replace('"example/project"', '"example/other"'),
                   GOOD_ADAPTER + '\ncall("pr", "comment", "42", "--repo", "example/project", "--body", body)\n',
                   'print("Done")')
        for script in scripts:
            with tempfile.TemporaryDirectory() as directory:
                _, result = self.trial(directory, "publish", script)
                self.assertFalse(result["pass"])

    def test_fixture_and_results_cannot_be_reused_or_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.trial(directory, "publish", GOOD_ADAPTER)
            with self.assertRaisesRegex(ValueError, "already used"):
                wf.run(root, [sys.executable, "-c", "print('done')"], "scripted")
            with self.assertRaisesRegex(ValueError, "Scores already exist"):
                wf.score(root)
            untouched = Path(directory) / "fresh"
            wf.prepare(untouched, "publish")
            (untouched / "repo/notes.txt").write_text("changed before run")
            with self.assertRaisesRegex(ValueError, "fixture changed"):
                wf.run(untouched, [sys.executable, "-c", "print('done')"], "scripted")


if __name__ == "__main__":
    unittest.main()
