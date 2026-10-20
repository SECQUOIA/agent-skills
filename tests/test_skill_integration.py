"""Actual Git histories demonstrate integration decisions without real-repo writes."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "integration", ROOT / "skills/apply-conversation-lessons/scripts/plan_integration.py")
integration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(integration)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.base = self.add_commit("base.txt", "base")
        self.git("checkout", "-b", "learnings/test")
        self.original = self.add_commit("pending.txt", "pending")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args],
                                       text=True, stderr=subprocess.DEVNULL).strip()

    def add_commit(self, path, body):
        (self.repo / path).write_text(body)
        self.git("add", "--", path)
        self.git("commit", "-m", body)
        return self.git("rev-parse", "HEAD")

    def get_plan(self, synced, result, upstream=None):
        before = self.git("status", "--porcelain=v1")
        tip = self.git("rev-parse", "HEAD")
        output = integration.plan(self.repo, "learnings/test", self.original,
                                  upstream or self.base, synced, result, "main")
        self.assertEqual(self.git("status", "--porcelain=v1"), before)
        self.assertEqual(self.git("rev-parse", "HEAD"), tip)
        self.assertFalse(output["mutations_performed"])
        return output

    def test_unchanged_sync_can_fast_forward(self):
        self.git("checkout", "-b", "work")
        result = self.add_commit("lesson.txt", "new lesson")
        self.git("checkout", "learnings/test")
        output = self.get_plan(self.original, result)
        self.assertEqual(output["mode"], "fast_forward")
        self.assertEqual(output["lesson_commits"], [result])

    def test_rewritten_unique_commit_requires_reconciliation(self):
        self.git("checkout", "main")
        upstream = self.add_commit("upstream.txt", "upstream")
        self.git("checkout", "-b", "work", self.original)
        self.git("rebase", upstream)
        synced = self.git("rev-parse", "HEAD")
        result = self.add_commit("lesson.txt", "new lesson")
        self.git("checkout", "learnings/test")
        output = self.get_plan(synced, result, upstream)
        self.assertEqual(output["mode"], "reconcile")
        self.assertEqual(output["lesson_commits"], [result])
        self.assertFalse(integration.ancestor(self.repo, self.original, result))

    def test_upstream_equivalent_commit_does_not_imply_ancestry(self):
        self.git("checkout", "main")
        self.add_commit("upstream.txt", "upstream")
        self.git("cherry-pick", self.original)
        upstream = self.git("rev-parse", "HEAD")
        self.git("checkout", "-b", "work", self.original)
        self.git("rebase", upstream)
        synced = self.git("rev-parse", "HEAD")
        result = self.add_commit("lesson.txt", "new lesson")
        self.git("checkout", "learnings/test")
        self.assertEqual(self.get_plan(synced, result, upstream)["mode"], "reconcile")

    def test_dirty_destination_and_concurrent_advance_are_preserved(self):
        self.git("checkout", "-b", "work")
        result = self.add_commit("lesson.txt", "new lesson")
        self.git("checkout", "learnings/test")
        (self.repo / "user.txt").write_text("uncommitted")
        self.assertEqual(self.get_plan(self.original, result)["mode"], "blocked")
        self.assertEqual((self.repo / "user.txt").read_text(), "uncommitted")
        self.add_commit("user.txt", "concurrent work")
        self.assertEqual(self.get_plan(self.original, result)["mode"], "blocked")

    def test_already_integrated_and_invalid_boundaries(self):
        result = self.add_commit("lesson.txt", "new lesson")
        self.assertEqual(self.get_plan(self.original, result)["mode"], "already_integrated")
        with self.assertRaisesRegex(ValueError, "does not descend"):
            self.get_plan(result, self.original)
        with self.assertRaisesRegex(ValueError, "default branch"):
            integration.plan(self.repo, "main", self.base, self.base, self.base, self.base, "main")

    def test_incoming_tracked_path_cannot_overwrite_ignored_user_file(self):
        self.original = self.add_commit(".gitignore", "local.txt\n")
        self.git("checkout", "-b", "work")
        (self.repo / "local.txt").write_text("incoming")
        self.git("add", "-f", "local.txt")
        self.git("commit", "-m", "track previously ignored path")
        result = self.git("rev-parse", "HEAD")
        self.git("checkout", "learnings/test")
        (self.repo / "local.txt").write_text("valuable user content")
        output = self.get_plan(self.original, result)
        self.assertEqual(output["mode"], "blocked")
        self.assertEqual(output["destination_worktrees"][0]["ignored_collisions"], ["local.txt"])
        merge = subprocess.run(["git", "-C", str(self.repo), "merge", "--ff-only",
                                "--no-overwrite-ignore", result], capture_output=True)
        self.assertNotEqual(merge.returncode, 0)
        self.assertEqual((self.repo / "local.txt").read_text(), "valuable user content")


if __name__ == "__main__":
    unittest.main()
