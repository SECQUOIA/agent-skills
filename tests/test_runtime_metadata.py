from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from test_encounter_ledger import hook_payload, ledger


class RuntimeMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = self.temporary.name

    def record(self, connection, **kwargs):
        values = dict(
            rule_id="GH-LIVE-STATE-001",
            workflow_id="owner/repo#1",
            workflow_label="owner/repo#1",
            agent="codex",
            outcome="escaped",
            revision="revision-a",
        )
        values.update(kwargs)
        return ledger.record_encounter(connection, **values)

    def test_mixed_models_preserve_each_outcome_without_splitting_episode(self):
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            first = self.record(
                connection,
                model="model-a",
                reasoning_effort="high",
                client_version="client-1",
                harness_version="harness-2",
            )
            second = self.record(
                connection, model="model-b", agent="claude", outcome="passed"
            )
            self.assertEqual(first, second)
            report = ledger.report_encounters(connection, min_encounters=1)[0]
            self.assertEqual(report["opportunities"], 1)
            self.assertEqual(report["violations"], 1)
            self.assertEqual(report["recorded_observations"], 2)
            cohorts = {row["model"]: row for row in report["runtime_observations"]}
            self.assertEqual(cohorts["model-a"]["escaped"], 1)
            self.assertEqual(cohorts["model-b"]["passed"], 1)
            self.assertEqual(cohorts["model-b"]["escaped"], 0)
            self.assertEqual(cohorts["model-a"]["reasoning_effort"], "high")
            self.assertEqual(cohorts["model-a"]["client_version"], "client-1")
            self.assertEqual(cohorts["model-a"]["harness_version"], "harness-2")
            self.assertIn("not causal model attribution", report["attribution_note"])

    def test_legacy_report_stays_read_only_and_migration_does_not_invent_history(self):
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            self.record(connection)
            self.record(connection)
            connection.execute("DROP TABLE encounter_observations")
            connection.commit()
        database = Path(self.state) / "encounters.sqlite3"
        before = database.read_bytes()
        with ledger.report_database(self.state) as connection:
            row = ledger.report_encounters(connection, min_encounters=1)[0]
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual(row["runtime_observations"], [])
        self.assertEqual(row["unattributed_legacy_observations"], 2)
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            self.record(connection, model="model-new", outcome="passed")
            row = ledger.report_encounters(connection, min_encounters=1)[0]
            self.assertEqual(row["opportunities"], 1)
            self.assertEqual(row["unattributed_legacy_observations"], 2)
            self.assertEqual(row["recorded_observations"], 1)
            self.assertEqual(row["runtime_observations"][0]["escaped"], 0)
        # Reopening is idempotent, including mixed-version legacy attempts.
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            connection.execute("UPDATE encounters SET attempts = attempts + 1")
            connection.commit()
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            row = ledger.report_encounters(connection, min_encounters=1)[0]
            self.assertEqual(row["unattributed_legacy_observations"], 3)

    def test_missing_hook_metadata_is_null_and_later_model_does_not_backfill_it(self):
        for metadata in (
            {},
            {
                "model_slug": "model-b",
                "reasoning_effort": "medium",
                "client_version": "client-2",
                "harness_version": "harness-3",
            },
        ):
            ledger.run_hook(
                hook_payload(
                    "PreToolUse",
                    "gh pr comment 1 --repo owner/repo --body done",
                    **metadata,
                ),
                agent="codex",
                mode="audit",
                explicit_state_dir=self.state,
            )
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            rows = connection.execute(
                "SELECT * FROM encounter_observations ORDER BY id"
            ).fetchall()
            self.assertEqual(len(rows), 2)
            for key in ledger.RUNTIME_FIELDS:
                self.assertIsNone(rows[0][key])
            self.assertEqual(rows[1]["model"], "model-b")
            self.assertEqual(rows[1]["reasoning_effort"], "medium")
            self.assertEqual(rows[1]["event"], "PreToolUse")

    def test_boundary_runtime_is_observer_context_and_never_carried_to_next_event(self):
        command = "gh pr comment 2 --repo owner/repo --body done"
        ledger.run_hook(
            hook_payload("PreToolUse", command, model="writer-model"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state,
        )
        ledger.run_hook(
            hook_payload("UserPromptSubmit", model="observer-model"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state,
        )
        ledger.run_hook(
            hook_payload("PreToolUse", command),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state,
        )
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            rows = connection.execute(
                "SELECT model, event FROM encounter_observations ORDER BY id"
            ).fetchall()
            self.assertEqual(
                [tuple(row) for row in rows],
                [
                    ("writer-model", "PreToolUse"),
                    ("observer-model", "UserPromptSubmit"),
                    (None, "PreToolUse"),
                ],
            )

    def test_cli_labels_round_trip_and_human_report_explains_scope(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = ledger.main(
                [
                    "record",
                    "--rule-id",
                    "GH-LIVE-STATE-001",
                    "--workflow-id",
                    "owner/repo#3",
                    "--agent",
                    "codex",
                    "--outcome",
                    "escaped",
                    "--skill-revision",
                    "abc",
                    "--model",
                    "model-c",
                    "--reasoning-effort",
                    "high",
                    "--client-version",
                    "1.2.3",
                    "--harness-version",
                    "build-7",
                    "--state-dir",
                    self.state,
                ]
            )
        self.assertEqual(result, 0)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ledger.main(["report", "--min-encounters", "1", "--state-dir", self.state])
        self.assertIn("model=model-c", output.getvalue())
        self.assertIn("harness_version=build-7", output.getvalue())
        self.assertIn("not causal model attribution", output.getvalue())

    def test_privacy_allowlist_ignores_nested_metadata_commands_and_transcripts(self):
        secret = "PRIVATE_TRANSCRIPT_MARKER"
        transcript = Path(self.state) / "private-transcript.jsonl"
        transcript.write_text(secret)
        payload = hook_payload(
            "PreToolUse",
            f"gh pr comment 4 --repo owner/repo --body {secret}",
            model={"name": secret},
            reasoning_effort=[secret],
            client_version="sk-private-token",
            harness_version="Bearer private-token",
            transcript_path=str(transcript),
            prompt=secret,
            metadata={"model": secret},
            tool_response={"model": secret},
        )
        ledger.run_hook(
            payload, agent="codex", mode="audit", explicit_state_dir=self.state
        )
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            persisted = "\n".join(connection.iterdump())
            row = connection.execute("SELECT * FROM encounter_observations").fetchone()
            for field in ledger.RUNTIME_FIELDS:
                self.assertIsNone(row[field])
        for value in (
            secret,
            str(transcript),
            "sk-private-token",
            "Bearer private-token",
        ):
            self.assertNotIn(value, persisted)
        self.assertEqual(transcript.read_text(), secret)
        self.assertIsNone(ledger._runtime_label("x" * 129))
        self.assertIsNone(ledger._runtime_label("model\nprivate text"))
        self.assertEqual(
            ledger._payload_runtime({"hook_event_name": []})["event"], "unknown"
        )


if __name__ == "__main__":
    unittest.main()
