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


def claude_payload(event: str, command: str = "", response=None, **extra):
    """A payload in the exact shape Claude Code v2.1.x sends: no turn_id, and
    Bash tool_response carries stdout/stderr without an exit code (PostToolUse
    only fires for successful tool calls)."""
    payload = {
        "session_id": "claude-session-1",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/tmp",
        "permission_mode": "acceptEdits",
        "hook_event_name": event,
    }
    if command:
        payload.update(
            {
                "tool_name": "Bash",
                "tool_input": {"command": command, "description": "run"},
                "tool_use_id": "toolu_0123",
            }
        )
    if response is not None:
        payload["tool_response"] = response
        payload["duration_ms"] = 10
    payload.update(extra)
    return payload


CLAUDE_BASH_OK = {
    "stdout": "output",
    "stderr": "",
    "interrupted": False,
    "isImage": False,
    "noOutputExpected": False,
}


class ClaudeHookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state_dir = self.temporary.name

    def tearDown(self):
        self.temporary.cleanup()

    def run_hook(self, payload, mode="audit"):
        return ledger.run_hook(
            payload,
            agent="claude",
            mode=mode,
            explicit_state_dir=self.state_dir,
        )

    def test_claude_shapes_audit_flow_records_agent_and_never_blocks(self):
        write = "gh pr comment 11 --repo owner/repo --body done"
        pre = self.run_hook(claude_payload("PreToolUse", write))
        self.assertIn("additionalContext", pre["hookSpecificOutput"])
        self.assertNotIn("permissionDecision", pre["hookSpecificOutput"])

        self.run_hook(claude_payload("PostToolUse", write, CLAUDE_BASH_OK))
        stop = self.run_hook(claude_payload("Stop", stop_hook_active=False))
        self.assertNotIn("decision", stop)
        self.assertIn("systemMessage", stop)

        connection = ledger.connect_database(self.state_dir)
        try:
            rows = connection.execute("SELECT * FROM encounters").fetchall()
        finally:
            connection.close()
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["last_agent"], "claude")
            self.assertNotEqual(row["last_skill_revision"], "")

    def test_claude_shapes_satisfy_rules_with_successful_reads(self):
        read = "gh pr view 11 --repo owner/repo --json state"
        write = "gh pr comment 11 --repo owner/repo --body done"
        self.run_hook(claude_payload("PostToolUse", read, CLAUDE_BASH_OK))
        self.assertIsNone(self.run_hook(claude_payload("PreToolUse", write)))
        self.run_hook(claude_payload("PostToolUse", write, CLAUDE_BASH_OK))
        self.run_hook(claude_payload("PostToolUse", read, CLAUDE_BASH_OK))
        stop = self.run_hook(claude_payload("Stop", stop_hook_active=False))
        self.assertEqual(stop, {})

    def test_claude_enforcement_denies_and_respects_stop_reentry(self):
        write = "gh issue comment 12 --repo owner/repo --body done"
        denied = self.run_hook(claude_payload("PreToolUse", write), mode="enforce")
        self.assertEqual(
            denied["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.run_hook(
            claude_payload("PostToolUse", write, CLAUDE_BASH_OK), mode="enforce"
        )
        stop = self.run_hook(
            claude_payload("Stop", stop_hook_active=False), mode="enforce"
        )
        self.assertEqual(stop["decision"], "block")
        reentry = self.run_hook(
            claude_payload("Stop", stop_hook_active=True), mode="enforce"
        )
        self.assertNotIn("decision", reentry)

    def test_claude_and_codex_share_one_ledger_episode(self):
        write = "gh pr comment 11 --repo owner/repo --body done"
        self.run_hook(claude_payload("PreToolUse", write))
        ledger.run_hook(
            {
                "session_id": "codex-session",
                "turn_id": "turn-9",
                "cwd": "/tmp",
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": write},
            },
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        connection = ledger.connect_database(self.state_dir)
        try:
            rows = connection.execute(
                "SELECT * FROM encounters WHERE rule_id='GH-LIVE-STATE-001'"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attempts"], 2)
        self.assertEqual(json.loads(rows[0]["agents_json"]), ["claude", "codex"])


class ClaudeInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temporary.name) / "settings.json"

    def tearDown(self):
        self.temporary.cleanup()

    def existing_settings(self):
        return {
            "model": "opus",
            "permissions": {"allow": ["Bash(git status:*)"], "deny": []},
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "python3 other.py"}],
                    }
                ]
            },
        }

    def owned_handlers(self, document):
        return [
            handler
            for groups in document.get("hooks", {}).values()
            for group in groups
            for handler in group["hooks"]
            if ledger.INSTALLATION_ID in handler.get("command", "")
        ]

    def test_install_is_idempotent_and_preserves_unrelated_settings(self):
        self.settings_path.write_text(
            json.dumps(self.existing_settings()), encoding="utf-8"
        )
        script = Path("/opt/secquoia/encounter ledger.py")
        _, first_backup = ledger.install_claude_hooks(
            self.settings_path, script, "audit"
        )
        self.assertIsNotNone(first_backup)
        self.assertTrue(first_backup.exists())
        _, second_backup = ledger.install_claude_hooks(
            self.settings_path, script, "audit"
        )
        self.assertIsNone(second_backup)

        document = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(document["model"], "opus")
        self.assertEqual(
            document["permissions"], self.existing_settings()["permissions"]
        )
        owned = self.owned_handlers(document)
        self.assertEqual(len(owned), 3)
        for handler in owned:
            self.assertIn("--agent claude", handler["command"])
            self.assertIn("--mode audit", handler["command"])
            self.assertIn("'/opt/secquoia/encounter ledger.py'", handler["command"])
            self.assertNotIn("statusMessage", handler)
        unowned = [
            handler["command"]
            for groups in document["hooks"].values()
            for group in groups
            for handler in group["hooks"]
            if ledger.INSTALLATION_ID not in handler.get("command", "")
        ]
        self.assertEqual(unowned, ["python3 other.py"])
        for event in ("PreToolUse", "PostToolUse"):
            matchers = [
                group.get("matcher")
                for group in document["hooks"][event]
                for handler in group["hooks"]
                if ledger.INSTALLATION_ID in handler.get("command", "")
            ]
            self.assertEqual(matchers, ["Bash"])

    def test_install_creates_settings_file_when_missing(self):
        path, backup = ledger.install_claude_hooks(
            self.settings_path, Path("/opt/ledger.py"), "audit"
        )
        self.assertIsNone(backup)
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(self.owned_handlers(document)), 3)

    def test_uninstall_removes_only_owned_handlers(self):
        self.settings_path.write_text(
            json.dumps(self.existing_settings()), encoding="utf-8"
        )
        ledger.install_claude_hooks(self.settings_path, Path("/opt/ledger.py"), "audit")
        _, backup, changed = ledger.uninstall_claude_hooks(self.settings_path)
        self.assertTrue(changed)
        self.assertTrue(backup.exists())
        document = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(self.owned_handlers(document), [])
        self.assertEqual(document["model"], "opus")
        remaining = [
            handler["command"]
            for groups in document["hooks"].values()
            for group in groups
            for handler in group["hooks"]
        ]
        self.assertEqual(remaining, ["python3 other.py"])

        _, _, changed_again = ledger.uninstall_claude_hooks(self.settings_path)
        self.assertFalse(changed_again)

    def test_install_preserves_existing_file_mode(self):
        self.settings_path.write_text(
            json.dumps(self.existing_settings()), encoding="utf-8"
        )
        self.settings_path.chmod(0o644)
        ledger.install_claude_hooks(self.settings_path, Path("/opt/ledger.py"), "audit")
        self.assertEqual(self.settings_path.stat().st_mode & 0o777, 0o644)


if __name__ == "__main__":
    unittest.main()
