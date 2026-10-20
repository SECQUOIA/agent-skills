from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills/apply-conversation-lessons/scripts/encounter_ledger.py"
)
SPEC = importlib.util.spec_from_file_location("worker_audit_ledger", MODULE_PATH)
assert SPEC and SPEC.loader
ledger = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ledger
SPEC.loader.exec_module(ledger)


class WorkerPublicationAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = self.directory.name
        self.revision = mock.patch.object(ledger, "skill_revision", return_value="test-revision")
        self.revision.start()
        self.addCleanup(self.revision.stop)

    def hook(self, command, *, client="claude", event="PreToolUse", mode="audit", **extra):
        payload = {
            "session_id": "private-session",
            "turn_id": "private-turn",
            "cwd": "/tmp",
            "hook_event_name": event,
            "tool_name": "Bash",
            "tool_input": {"command": command},
            **extra,
        }
        return ledger.run_hook(payload, agent=client, mode=mode, explicit_state_dir=self.state)

    def observations(self):
        with ledger.report_database(self.state) as connection:
            return ledger.report_remote_write_observations(connection)

    def test_literal_git_push_recognition(self):
        for command in (
            "git push", "git push origin HEAD", "git -C /tmp -c color.ui=false push --force-with-lease origin HEAD",
            "git --git-dir=/tmp/repo.git push --tags", "git -C/tmp push -u origin HEAD",
            "git push --push-option --dry-run origin HEAD", "git push --repo origin --receive-pack receive-pack HEAD",
            "git push --dry-run --no-dry-run origin HEAD", "git push -- origin --dry-run",
            "env TASK=1 git push origin HEAD", "command git push origin HEAD",
            "sh -c 'git push origin HEAD'", "echo ready && git push origin HEAD",
            "printf '%s' $(git push origin HEAD)",
        ):
            with self.subTest(command=command):
                self.assertTrue(ledger._has_literal_git_push(command))

    def test_reads_local_operations_dry_runs_and_inert_text_do_not_count(self):
        for command in (
            "git status", "git commit -m push", "git fetch origin", "git log --grep push",
            "git push -n origin HEAD", "git push -fn origin HEAD", "git push --dry-run origin HEAD",
            "git push --no-dry-run --dry-run origin HEAD", "git push --help", "git --help push",
            "git -c alias.publish=push publish", "git push --unknown-option origin HEAD",
            "git push -o", "git push origin $BRANCH", "echo git push origin HEAD",
            "printf '%s' 'git push origin HEAD'", "echo '$(git push origin HEAD)'",
            "echo sh -c 'git push origin HEAD'", "python publish.py",
        ):
            with self.subTest(command=command):
                self.assertFalse(ledger._has_literal_git_push(command))

    def test_comments_and_heredoc_text_are_not_audit_attempts(self):
        for operation in ("git push", "gh pr close 11 --repo o/r"):
            for command in (
                f"echo ready # ignored ; {operation}",
                f"# {operation}",
                f"cat <<'EOF'\n{operation}\nEOF",
                f'cat <<"EOF"\n{operation}\nEOF\n',
                f"cat <<EOF\n{operation}\nEOF\n",
                f"cat <<-'EOF'\n\t{operation}\n\tEOF\n",
                f"cat <<'EOF'\n$({operation})\nEOF\n",
                f"sh -c 'echo ready # ignored ; {operation}'",
                f"echo 'literal # {operation}'",
            ):
                with self.subTest(command=command):
                    self.assertEqual(ledger._audit_remote_write_kinds(command, "/tmp"), set())
                    self.hook(command, agent_id="worker")
        self.assertEqual(self.observations()["observations"], [])

    def test_real_commands_after_comments_or_heredocs_and_literal_hashes_are_observed(self):
        for operation, kind in (("git push", "git-push"), ("gh pr close 11 --repo o/r", "gh-write")):
            for command in (
                f"echo ready # ignored ; git status\n{operation}",
                f"cat <<'EOF'\ninert\nEOF\n{operation}",
                f"cat <<-'EOF'\n\tinert\n\tEOF\n{operation}",
                f"cat <<ONE <<'TWO'\ninert\nONE\nmore data\nTWO\n{operation}",
                f"printf '%s' 'literal # text'; {operation}",
                f'printf "%s" "literal # text"; {operation}',
                f"echo unquoted#text; {operation}",
                f"echo escaped\\ #text; {operation}",
                f"echo \\#text; {operation}",
                f'echo "$({operation})"',
                f"sh -c 'echo ready # comment\n{operation}'",
            ):
                with self.subTest(command=command):
                    self.assertEqual(ledger._audit_remote_write_kinds(command, "/tmp"), {kind})

    def test_unsupported_heredocs_are_skipped_instead_of_scanning_their_data(self):
        for command in (
            "cat <<E'OF'\ngit push\nEOF\n",
            "cat <<EOF\ngit push\n",  # Unterminated document.
            "cat <<EOF\n$(git push)\nEOF\n",  # Body expansions are outside coverage.
            "cat <<< 'git push'",
        ):
            with self.subTest(command=command):
                self.assertEqual(ledger._audit_remote_write_kinds(command, "/tmp"), set())

    def test_attempts_have_reported_role_provenance_without_authorization_claims(self):
        self.hook("git push origin HEAD", agent_id="private-worker", model="test-model")
        self.hook("git push origin HEAD")  # Solo/main-shaped payload: role stays unknown.
        self.hook("git push origin HEAD", client="codex", agent_id="private-codex-worker")
        self.hook("git push origin HEAD", client="unknown", agent_id={"unexpected": "shape"})
        audit = self.observations()
        self.assertFalse(audit["authorization_assessed"])
        self.assertEqual(
            {(row["agent"], row["reported_role"], row["role_source"]) for row in audit["observations"]},
            {
                ("claude", "worker", "claude.agent_id"),
                ("claude", "unknown", "missing-agent-id"),
                ("codex", "unknown", "unvalidated-client.agent_id"),
                ("unknown", "unknown", "missing-agent-id"),
            },
        )
        worker = next(row for row in audit["observations"] if row["reported_role"] == "worker")
        self.assertEqual(worker["runtime"]["model"], "test-model")
        self.assertIn("not completed writes", audit["coverage_note"])
        self.assertIn("explicitly authorized", audit["coverage_note"])

    def test_valid_gh_preflight_is_not_newly_denied_in_enforce_mode(self):
        self.hook(
            "gh pr view 11 --repo o/r", event="PostToolUse", mode="enforce",
            agent_id="worker", tool_response={"stdout": "open"},
        )
        result = self.hook(
            "gh pr comment 11 --repo o/r --body done", mode="enforce", agent_id="worker",
            publisher=True, publication_grant="untrusted-field-is-not-a-grant",
        )
        self.assertIsNone(result)
        self.assertIsNone(self.hook("git push origin HEAD", mode="enforce", agent_id="worker"))
        self.assertEqual({row["operation"] for row in self.observations()["observations"]}, {"git-push", "gh-write"})
        with ledger.report_database(self.state) as connection:
            self.assertEqual(ledger.report_encounters(connection, min_encounters=1), [])
            outcomes = connection.execute("SELECT outcome FROM encounters").fetchall()
            self.assertEqual([row["outcome"] for row in outcomes], ["passed"])

    def test_existing_gh_denial_stays_unchanged_and_audit_is_an_attempt(self):
        result = self.hook("gh pr close 11 --repo o/r", mode="enforce", agent_id="worker")
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        rows = self.observations()["observations"]
        self.assertEqual(rows[0]["attempts"], 1)
        self.assertEqual(rows[0]["operation"], "gh-write")

    def test_reads_local_git_dry_run_and_post_events_do_not_add_observations(self):
        for command in ("gh pr view 11 --repo o/r", "git commit -m done", "git push --dry-run origin HEAD"):
            self.hook(command, agent_id="worker")
        self.hook("git push origin HEAD", agent_id="worker", event="PostToolUse", tool_response={})
        self.assertEqual(self.observations()["observations"], [])

    def test_api_mutation_and_push_share_attempt_without_recording_local_gh_setting(self):
        self.hook(
            "gh api repos/o/r/issues/11 -X PATCH -f state=closed && git push origin HEAD",
            agent_id="worker", tool_use_id="combined-tool",
        )
        self.hook("gh repo set-default o/r", agent_id="worker")
        self.assertEqual(
            {row["operation"]: row["attempts"] for row in self.observations()["observations"]},
            {"gh-write": 1, "git-push": 1},
        )

    def test_hook_open_prunes_old_observations_without_changing_encounters(self):
        self.hook("git push origin HEAD", agent_id="worker")
        connection = ledger.connect_database(self.state)
        try:
            with connection:
                connection.execute(
                    "UPDATE remote_write_observations SET observed_at = ?",
                    (ledger.isoformat(ledger.utc_now() - timedelta(days=31)),),
                )
        finally:
            connection.close()
        with ledger.report_database(self.state) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM remote_write_observations").fetchone()[0], 1)
        self.hook("git status")
        self.assertEqual(self.observations()["observations"], [])

    def test_tool_retries_deduplicate_per_worker_without_persisting_command_or_raw_ids(self):
        command = "git push --push-option confidential-option origin HEAD"
        for worker in ("private-worker-one", "private-worker-one", "private-worker-two"):
            self.hook(command, agent_id=worker, tool_use_id="private-tool")
        self.hook(command, agent_id="private-worker-one")
        self.hook(command, agent_id="private-worker-one")
        self.assertEqual(sum(row["attempts"] for row in self.observations()["observations"]), 4)
        with ledger.report_database(self.state) as connection:
            rows = connection.execute("SELECT * FROM remote_write_observations").fetchall()
            persisted = str([dict(row) for row in rows])
            for private in ("confidential-option", "private-worker", "private-session", "private-tool"):
                self.assertNotIn(private, persisted)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM encounters").fetchone()[0], 0)

    def test_audit_report_preserves_default_json_contract_and_handles_absent_or_legacy_state(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            ledger.main(["report", "--remote-write-audit", "--json", "--state-dir", self.state])
        self.assertEqual(json.loads(output.getvalue())["observations"], [])
        self.assertFalse((Path(self.state) / "encounters.sqlite3").exists())
        self.hook("git push origin HEAD", agent_id="worker")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            ledger.main(["report", "--json", "--state-dir", self.state])
        self.assertEqual(json.loads(output.getvalue()), [])
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        self.assertEqual(ledger.report_remote_write_observations(connection)["observations"], [])


if __name__ == "__main__":
    unittest.main()
