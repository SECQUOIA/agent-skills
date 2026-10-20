from __future__ import annotations

import contextlib
import io
import json
import shlex
import tempfile
import unittest
from pathlib import Path

from test_encounter_ledger import hook_payload, ledger


class TargetResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = str(self.root / "state")

    def classify(self, command):
        return ledger.classify_gh_operations(command, str(self.root))[0]

    def hook(self, event, command="", *, mode="enforce", agent="codex"):
        response = {"exit_code": 0} if event == "PostToolUse" else None
        return ledger.run_hook(
            hook_payload(event, command, response, model="test-observer"),
            agent=agent,
            mode=mode,
            explicit_state_dir=self.state,
        )

    def assert_verified(self, read, write, *, agent="codex"):
        read_op, write_op = map(self.classify, (read, write))
        self.assertEqual(read_op.kind, "read")
        self.assertTrue(read_op.read_eligible)
        self.assertEqual(write_op.kind, "write")
        self.assertEqual(read_op.workflow_key, write_op.workflow_key)
        self.hook("PostToolUse", read, agent=agent)
        self.assertIsNone(self.hook("PreToolUse", write, agent=agent))
        self.hook("PostToolUse", write, agent=agent)
        self.hook("PostToolUse", read, agent=agent)
        self.assertEqual(self.hook("Stop", agent=agent), {})
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            rows = connection.execute(
                "SELECT outcome, target_resolution FROM encounters"
            ).fetchall()
        self.assertTrue(rows)
        self.assertEqual({tuple(row) for row in rows}, {("passed", "tracked_target")})

    def test_file_node_read_and_mutation_pass_both_hooks_for_both_agents(self):
        query = self.root / "query.graphql"
        query.write_text(
            "query Read($id:ID!) { node(id:$id) { ... on Issue { state } } }"
        )
        mutation = self.root / "mutation.graphql"
        mutation.write_text(
            "mutation Close($issueId:ID!) { closeIssue(input:{issueId:$issueId}) { issue { state } } }"
        )
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                self.state = str(self.root / agent)
                self.assert_verified(
                    f"GH_REPO=owner/repo gh api graphql -F id=I_one -F query=@{query}",
                    f"GH_REPO=owner/repo gh api graphql -F issueId=I_one -F query=@{mutation}",
                    agent=agent,
                )

    def test_global_node_ids_do_not_require_an_ambient_repository(self):
        self.assert_verified(
            "gh api graphql -f 'query={ node(id:\"I_one\") { id } }'",
            "gh api graphql -f 'query=mutation { closeIssue(input:{issueId:\"I_one\"}) { issue { id } } }'",
        )

    def test_static_inline_variables_and_literal_node_ids_match(self):
        read = "GH_REPO=owner/repo gh api graphql -F target=I_one -f 'query=query Read($target:ID!) { node(id:$target) { ... on Issue { state } } }'"
        writes = (
            "GH_REPO=owner/repo gh api graphql -F target=I_one -f 'query=mutation Close($target:ID!) { closeIssue(input:{issueId:$target}) { issue { state } } }'",
            "GH_REPO=owner/repo gh api graphql -f 'query=mutation { closeIssue(input:{issueId:\"I_one\"}) { issue { state } } }'",
        )
        for index, write in enumerate(writes):
            with self.subTest(write=write):
                self.state = str(self.root / str(index))
                self.assert_verified(read, write)

    def test_escaped_variables_and_attached_flags_preserve_literal_provenance(self):
        read = r'GH_REPO=owner/repo gh api graphql -Fid=I_one --raw-field="query=query Read(\$id:ID!) { node(id:\$id) { ... on Issue { state } } }"'
        write = "GH_REPO=owner/repo gh api graphql -FissueId=I_one -f'query=mutation Close($issueId:ID!) { closeIssue(input:{issueId:$issueId}) { issue { state } } }'"
        self.assert_verified(read, write)

    def test_interpolated_or_reconstructed_queries_cannot_bind_target(self):
        mutation = "mutation Close($issueId:ID!) { closeIssue(input:{issueId:$issueId}) { issue { state } } }"
        cases = (
            f'GH_REPO=owner/repo gh api graphql -F issueId=I_one -f "query={mutation}"',
            f"GH_REPO=owner/repo gh api graphql -F issueId=I_one -f 'query={mutation}'\"$EXTRA\"",
            f'env -S "GH_REPO=owner/repo gh api graphql" -F issueId=I_one -f "query={mutation}"',
            f"bash -c \"GH_REPO=owner/repo gh api graphql -F issueId=I_one -f 'query={mutation}'\"",
        )
        for command in cases:
            with self.subTest(command=command):
                operation = self.classify(command)
                self.assertEqual(operation.kind, "write")
                self.assertIn(":graphql:", operation.workflow_key)
                self.assertFalse(operation.read_eligible)

    def test_different_node_multi_node_and_opaque_alias_never_authorize(self):
        read = (
            "GH_REPO=owner/repo gh api graphql -f 'query={ node(id:\"I_one\") { id } }'"
        )
        self.hook("PostToolUse", read)
        writes = (
            "GH_REPO=owner/repo gh api graphql -f 'query=mutation { closeIssue(input:{issueId:\"I_two\"}) { issue { id } } }'",
            'GH_REPO=owner/repo gh api graphql -f \'query=mutation { a:closeIssue(input:{issueId:"I_one"}) { issue { id } } b:closeIssue(input:{issueId:"I_two"}) { issue { id } } }\'',
            "GH_REPO=owner/repo gh api graphql -F target=\"$ID\" -f 'query=mutation Close($target:ID!) { closeIssue(input:{issueId:$target}) { issue { id } } }'",
        )
        for command in writes:
            with self.subTest(command=command):
                denied = self.hook("PreToolUse", command)
                self.assertEqual(
                    denied["hookSpecificOutput"]["permissionDecision"], "deny"
                )

    def test_additional_unsupported_mutation_cannot_inherit_a_known_target(self):
        document = (
            'mutation { closeIssue(input:{issueId:"I_one"}) { issue { id } } '
            'resolveReviewThread(input:{threadId:"T_other"}) { clientMutationId } }'
        )
        operation = self.classify(
            f"GH_REPO=owner/repo gh api graphql -f {shlex.quote('query=' + document)}"
        )
        self.assertIn(":graphql:", operation.workflow_key)
        self.assertFalse(operation.read_eligible)

    def test_id_shaped_text_in_a_body_does_not_bind_a_target(self):
        document = 'mutation { addComment(input:{body:"issueId:\\"I_one\\""}) { clientMutationId } }'
        operation = self.classify(
            f"GH_REPO=owner/repo gh api graphql -f {shlex.quote('query=' + document)}"
        )
        self.assertIn(":graphql:", operation.workflow_key)

    def test_escaped_triple_quotes_in_body_cannot_spoof_a_node_target(self):
        document = (
            r'mutation { addComment(input:{body:""" text \""" issueId:"I_one" '
            r'more """, subjectId:"I_two"}) { subject { id } } }'
        )
        read = (
            "GH_REPO=owner/repo gh api graphql -f 'query={ node(id:\"I_one\") { id } }'"
        )
        write = (
            f"GH_REPO=owner/repo gh api graphql -f {shlex.quote('query=' + document)}"
        )
        self.hook("PostToolUse", read)
        operation = self.classify(write)
        self.assertIn(":graphql:", operation.workflow_key)
        denied = self.hook("PreToolUse", write)
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_dynamic_api_cannot_be_cleared_by_same_bucket_or_literal_read(self):
        self.hook("PostToolUse", 'GH_REPO=owner/repo gh api "$TARGET"')
        write = 'GH_REPO=owner/repo gh api -X PATCH "$TARGET"'
        denied = self.hook("PreToolUse", write)
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "coverage gap", denied["hookSpecificOutput"]["permissionDecisionReason"]
        )
        self.hook("PostToolUse", write)
        self.hook("PostToolUse", 'GH_REPO=owner/repo gh api "$OTHER"')
        self.hook("PostToolUse", "gh api repos/owner/repo/issues/11")
        stop = self.hook("Stop")
        self.assertEqual(stop["decision"], "block")
        self.assertIn("coverage gap", stop["reason"])
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            report = ledger.report_encounters(connection, min_encounters=1)
        self.assertEqual(len(report), 2)
        for row in report:
            self.assertEqual(row["violations"], 0)
            self.assertEqual(row["opportunities"], 0)
            self.assertEqual(row["distinct_targets"], 0)
            self.assertEqual(row["unresolved_target_episodes"], 1)
            self.assertFalse(row["eligible_for_lessons"])
            self.assertEqual(row["runtime_observations"][0]["prevented"], 0)
            self.assertEqual(row["runtime_observations"][0]["unresolved_target"], 1)

    def test_report_separates_real_violation_and_unsupported_graphql(self):
        unsupported = "GH_REPO=owner/repo gh api graphql -f 'query=mutation { unrecognized(input:{value:1}) { clientMutationId } }'"
        self.hook("PreToolUse", unsupported, mode="audit")
        self.hook(
            "PreToolUse", "gh pr comment 11 --repo owner/repo --body done", mode="audit"
        )
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            row = ledger.report_encounters(connection, min_encounters=2)[0]
        self.assertEqual(row["total_episodes"], 2)
        self.assertEqual(row["violations"], 1)
        self.assertEqual(row["opportunities"], 1)
        self.assertEqual(row["unresolved_target_episodes"], 1)
        self.assertFalse(row["eligible_for_lessons"])
        cohort = row["runtime_observations"][0]
        self.assertEqual(cohort["escaped"], 1)
        self.assertEqual(cohort["unresolved_target"], 1)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ledger.main(["report", "--state-dir", self.state])
        self.assertIn("1 unresolved episodes", output.getvalue())
        self.assertIn(
            "Conservative enforcement may still deny unsupported shapes",
            output.getvalue(),
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ledger.main(["report", "--json", "--state-dir", self.state])
        self.assertFalse(json.loads(output.getvalue())[0]["eligible_for_lessons"])

    def test_valid_repository_names_do_not_masquerade_as_unknown_sentinels(self):
        for name in ("unknown-repo", "unknown-host", "unknown-dynamic-repo"):
            operation = self.classify(f"gh pr view 11 --repo owner/{name}")
            self.assertTrue(operation.read_eligible)
            self.assertEqual(
                ledger._target_resolution(
                    operation.workflow_key, operation.workflow_label
                ),
                "tracked_target",
            )

    def test_legacy_uncertainty_inference_is_read_only_and_history_is_preserved(self):
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            ledger.record_encounter(
                connection,
                rule_id="GH-LIVE-STATE-001",
                workflow_id="github:github.com:owner/repo:graphql:oldhash",
                workflow_label="owner/repo:graphql",
                agent="claude",
                outcome="escaped",
                revision="old",
            )
            connection.execute("ALTER TABLE encounters DROP COLUMN target_resolution")
            connection.execute(
                "ALTER TABLE encounter_observations DROP COLUMN target_resolution"
            )
            connection.commit()
            old_rows = [
                tuple(row) for row in connection.execute("SELECT * FROM encounters")
            ]
        database = Path(self.state) / "encounters.sqlite3"
        before = database.read_bytes()
        with ledger.report_database(self.state) as connection:
            report = ledger.report_encounters(connection, min_encounters=1)[0]
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual(report["legacy_inferred_target_episodes"], 1)
        self.assertEqual(report["unresolved_target_episodes"], 1)
        self.assertEqual(report["violations"], 0)
        with contextlib.closing(ledger.connect_database(self.state)) as connection:
            new_rows = connection.execute("SELECT * FROM encounters").fetchall()
            self.assertEqual([tuple(row)[:-1] for row in new_rows], old_rows)
            self.assertEqual(new_rows[0]["target_resolution"], "legacy")
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM encounter_observations"
                ).fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main()
