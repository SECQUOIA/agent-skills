from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "apply-conversation-lessons"
    / "scripts"
    / "encounter_ledger.py"
)
SPEC = importlib.util.spec_from_file_location("encounter_ledger", MODULE_PATH)
assert SPEC and SPEC.loader
ledger = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ledger
SPEC.loader.exec_module(ledger)


def hook_payload(event: str, command: str = "", response=None, **extra):
    payload = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "cwd": "/tmp",
        "hook_event_name": event,
    }
    if command:
        payload.update(
            {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
        )
    if response is not None:
        payload["tool_response"] = response
    payload.update(extra)
    return payload


class EncounterLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state_dir = self.temporary.name

    def tearDown(self):
        self.temporary.cleanup()

    def connection(self):
        return ledger.connect_database(self.state_dir)

    def test_deduplicates_retries_and_agents_into_one_episode(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        connection = self.connection()
        try:
            first = ledger.record_encounter(
                connection,
                rule_id="GH-LIVE-STATE-001",
                workflow_id="github:o/r:number:11",
                workflow_label="o/r#11",
                agent="codex",
                outcome="passed",
                revision="aaa",
                now=start,
            )
            second = ledger.record_encounter(
                connection,
                rule_id="GH-LIVE-STATE-001",
                workflow_id="github:o/r:number:11",
                workflow_label="o/r#11",
                agent="claude",
                outcome="escaped",
                revision="bbb",
                now=start + timedelta(hours=1),
            )
            third = ledger.record_encounter(
                connection,
                rule_id="GH-LIVE-STATE-001",
                workflow_id="github:o/r:number:11",
                workflow_label="o/r#11",
                agent="codex",
                outcome="escaped",
                revision="bbb",
                now=start + timedelta(hours=26),
            )
            rows = connection.execute("SELECT * FROM encounters ORDER BY id").fetchall()
        finally:
            connection.close()

        self.assertEqual(first, second)
        self.assertNotEqual(second, third)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["attempts"], 2)
        self.assertEqual(json.loads(rows[0]["agents_json"]), ["claude", "codex"])
        self.assertEqual(rows[0]["outcome"], "escaped")
        self.assertEqual(rows[0]["first_skill_revision"], "aaa")
        self.assertEqual(rows[0]["last_skill_revision"], "bbb")

    def test_report_requires_three_independent_violation_episodes(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        connection = self.connection()
        try:
            for offset in (0, 25, 50):
                ledger.record_encounter(
                    connection,
                    rule_id="GH-WRITE-READBACK-001",
                    workflow_id="github:o/r:number:11",
                    workflow_label="o/r#11",
                    agent="codex",
                    outcome="escaped",
                    revision="aaa",
                    now=start + timedelta(hours=offset),
                )
            rows = ledger.report_encounters(
                connection,
                min_encounters=3,
                now=start + timedelta(hours=51),
            )
        finally:
            connection.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["violations"], 3)
        self.assertEqual(rows[0]["distinct_targets"], 1)

    def test_classifies_separate_and_compound_gh_operations(self):
        command = (
            "gh pr view 11 --repo owner/repo --json state; "
            "gh pr review 11 --repo owner/repo --approve"
        )
        operations = ledger.classify_gh_operations(command, "/tmp")
        self.assertEqual(
            [operation.kind for operation in operations], ["read", "write"]
        )
        self.assertEqual(
            {operation.workflow_label for operation in operations}, {"owner/repo#11"}
        )

        api = ledger.classify_gh_operations(
            "gh api --method POST repos/owner/repo/pulls/11/reviews --input /tmp/review.json",
            "/tmp",
        )
        self.assertEqual(len(api), 1)
        self.assertEqual(api[0].kind, "write")
        self.assertEqual(api[0].workflow_label, "owner/repo#11")

    def test_audit_records_missing_preflight_and_readback(self):
        write = "gh pr review 11 --repo owner/repo --approve"
        pre = ledger.run_hook(
            hook_payload("PreToolUse", write),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIn("additionalContext", pre["hookSpecificOutput"])

        ledger.run_hook(
            hook_payload("PostToolUse", write, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        stop = ledger.run_hook(
            hook_payload("Stop"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIn("systemMessage", stop)

        connection = self.connection()
        try:
            outcomes = {
                row["rule_id"]: row["outcome"]
                for row in connection.execute("SELECT rule_id, outcome FROM encounters")
            }
            pending = connection.execute(
                "SELECT COUNT(*) FROM hook_activity"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(outcomes["GH-LIVE-STATE-001"], "escaped")
        self.assertEqual(outcomes["GH-WRITE-READBACK-001"], "escaped")
        self.assertEqual(pending, 0)

    def test_separate_reads_satisfy_both_rules(self):
        read = "gh pr view 11 --repo owner/repo --json state"
        write = "gh pr review 11 --repo owner/repo --approve"
        for event, command in (
            ("PostToolUse", read),
            ("PostToolUse", write),
            ("PostToolUse", read),
        ):
            if command == write:
                pre = ledger.run_hook(
                    hook_payload("PreToolUse", command),
                    agent="codex",
                    mode="audit",
                    explicit_state_dir=self.state_dir,
                )
                self.assertIsNone(pre)
            ledger.run_hook(
                hook_payload(event, command, {"exit_code": 0}),
                agent="codex",
                mode="audit",
                explicit_state_dir=self.state_dir,
            )

        stop = ledger.run_hook(
            hook_payload("Stop"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertEqual(stop, {})
        connection = self.connection()
        try:
            outcomes = {
                row["rule_id"]: row["outcome"]
                for row in connection.execute("SELECT rule_id, outcome FROM encounters")
            }
        finally:
            connection.close()
        self.assertEqual(outcomes["GH-LIVE-STATE-001"], "passed")
        self.assertEqual(outcomes["GH-WRITE-READBACK-001"], "passed")

    def test_a_write_invalidates_the_previous_preflight(self):
        read = "gh pr view 11 --repo owner/repo --json state"
        first_write = "gh pr edit 11 --repo owner/repo --title updated"
        second_write = "gh pr comment 11 --repo owner/repo --body follow-up"
        ledger.run_hook(
            hook_payload("PostToolUse", read, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIsNone(
            ledger.run_hook(
                hook_payload("PreToolUse", first_write),
                agent="codex",
                mode="audit",
                explicit_state_dir=self.state_dir,
            )
        )
        ledger.run_hook(
            hook_payload("PostToolUse", first_write, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        result = ledger.run_hook(
            hook_payload("PreToolUse", second_write),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIn("additionalContext", result["hookSpecificOutput"])

    def test_enforcement_denies_and_stop_continues_once(self):
        write = "gh issue comment 12 --repo owner/repo --body done"
        denied = ledger.run_hook(
            hook_payload("PreToolUse", write),
            agent="codex",
            mode="enforce",
            explicit_state_dir=self.state_dir,
        )
        self.assertEqual(
            denied["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

        ledger.run_hook(
            hook_payload("PostToolUse", write, {"exit_code": 0}),
            agent="codex",
            mode="enforce",
            explicit_state_dir=self.state_dir,
        )
        stop = ledger.run_hook(
            hook_payload("Stop"),
            agent="codex",
            mode="enforce",
            explicit_state_dir=self.state_dir,
        )
        self.assertEqual(stop["decision"], "block")

        final_stop = ledger.run_hook(
            hook_payload("Stop", stop_hook_active=True),
            agent="codex",
            mode="enforce",
            explicit_state_dir=self.state_dir,
        )
        self.assertIn("systemMessage", final_stop)

    def test_codex_hook_install_is_idempotent_and_preserves_other_hooks(self):
        codex_home = Path(self.temporary.name) / "codex"
        codex_home.mkdir()
        hooks_path = codex_home / "hooks.json"
        hooks_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {"type": "command", "command": "python3 other.py"}
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        script = Path("/opt/secquoia/encounter ledger.py")
        ledger.install_codex_hooks(codex_home, script, "audit")
        ledger.install_codex_hooks(codex_home, script, "audit")
        document = json.loads(hooks_path.read_text(encoding="utf-8"))
        owned = [
            handler
            for groups in document["hooks"].values()
            for group in groups
            for handler in group["hooks"]
            if ledger.INSTALLATION_ID in handler.get("command", "")
        ]
        self.assertEqual(len(owned), 3)
        self.assertIn("'/opt/secquoia/encounter ledger.py'", owned[0]["command"])

        _, _, changed = ledger.uninstall_codex_hooks(codex_home)
        self.assertTrue(changed)
        document = json.loads(hooks_path.read_text(encoding="utf-8"))
        remaining = [
            handler["command"]
            for groups in document["hooks"].values()
            for group in groups
            for handler in group["hooks"]
        ]
        self.assertEqual(remaining, ["python3 other.py"])


if __name__ == "__main__":
    unittest.main()
