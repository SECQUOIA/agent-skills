from __future__ import annotations

import importlib.util
import json
import shlex
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def test_concurrent_encounters_keep_the_strongest_outcome_and_every_agent(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        inputs = [
            ("agent-passed", "passed"),
            ("agent-prevented", "prevented"),
            ("agent-escaped", "escaped"),
            ("agent-four", "passed"),
            ("agent-five", "prevented"),
            ("agent-six", "passed"),
        ]
        barrier = threading.Barrier(len(inputs))
        connect_lock = threading.Lock()

        def record(agent: str, outcome: str) -> None:
            # Opening a SQLite database sets WAL mode, which itself takes a lock;
            # serialize setup so the race exercised here is the ledger update.
            with connect_lock:
                connection = self.connection()
            try:
                barrier.wait(timeout=5)
                ledger.record_encounter(
                    connection,
                    rule_id="GH-LIVE-STATE-001",
                    workflow_id="github:o/r:number:concurrent",
                    workflow_label="o/r#concurrent",
                    agent=agent,
                    outcome=outcome,
                    revision="concurrent-revision",
                    now=start,
                )
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(inputs)) as executor:
            futures = [executor.submit(record, *item) for item in inputs]
            for future in futures:
                future.result(timeout=10)

        connection = self.connection()
        try:
            rows = connection.execute(
                "SELECT * FROM encounters WHERE workflow_label = 'o/r#concurrent'"
            ).fetchall()
        finally:
            connection.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attempts"], len(inputs))
        self.assertEqual(rows[0]["outcome"], "escaped")
        self.assertEqual(
            json.loads(rows[0]["agents_json"]),
            sorted(agent for agent, _ in inputs),
        )

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

    def test_report_unions_every_agent_recorded_in_each_episode(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        connection = self.connection()
        try:
            for offset in (0, 25, 50):
                episode_time = start + timedelta(hours=offset)
                ledger.record_encounter(
                    connection,
                    rule_id="GH-WRITE-READBACK-001",
                    workflow_id="github:o/r:number:11",
                    workflow_label="o/r#11",
                    agent="claude",
                    outcome="escaped",
                    revision="aaa",
                    now=episode_time,
                )
                ledger.record_encounter(
                    connection,
                    rule_id="GH-WRITE-READBACK-001",
                    workflow_id="github:o/r:number:11",
                    workflow_label="o/r#11",
                    agent="codex",
                    outcome="escaped",
                    revision="aaa",
                    now=episode_time + timedelta(minutes=1),
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
        self.assertEqual(rows[0]["agents"], ["claude", "codex"])

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

    def test_newlines_separate_a_github_read_from_a_following_write(self):
        command = (
            "gh pr view 11 --repo owner/repo --json state\n"
            "gh pr comment 11 --repo owner/repo --body done"
        )

        operations = ledger.classify_gh_operations(command, "/tmp")

        self.assertEqual(
            [operation.kind for operation in operations], ["read", "write"]
        )
        self.assertEqual(
            {operation.workflow_label for operation in operations}, {"owner/repo#11"}
        )

    def test_graphql_finds_query_field_independent_of_order_and_flag_spelling(self):
        query_path = Path(self.temporary.name) / "write-operation.graphql"
        query_path.write_text(
            "mutation UpdateTitle { updateIssue(input: {}) { clientMutationId } }",
            encoding="utf-8",
        )
        commands = (
            f"gh api graphql -F owner=owner -f query=@{query_path}",
            f"gh api graphql -f query=@{query_path} -F owner=owner",
            (f"gh api graphql --raw-field owner=owner --field query=@{query_path}"),
            (f"gh api graphql --field query=@{query_path} --raw-field owner=owner"),
        )

        for command in commands:
            with self.subTest(command=command):
                operations = ledger.classify_gh_operations(command, "/tmp")
                self.assertEqual(len(operations), 1)
                self.assertEqual(operations[0].kind, "write")

    def test_graphql_ignores_mutation_in_non_query_fields_and_filenames(self):
        query_path = Path(self.temporary.name) / "read-operation.graphql"
        mutation_named_path = Path(self.temporary.name) / "mutation-in-filename.graphql"
        for path in (query_path, mutation_named_path):
            path.write_text("query Viewer { viewer { login } }", encoding="utf-8")
        commands = (
            (f"gh api graphql --raw-field note=mutation --field query=@{query_path}"),
            f"gh api graphql --field query=@{mutation_named_path}",
            (f"gh api --raw-field owner=owner --field query=@{query_path} graphql"),
        )

        for command in commands:
            with self.subTest(command=command):
                operations = ledger.classify_gh_operations(command, "/tmp")
                self.assertEqual(len(operations), 1)
                self.assertEqual(operations[0].kind, "read")

    def test_graphql_mutation_inside_a_string_literal_is_still_a_read(self):
        query_path = Path(self.temporary.name) / "string-literal.graphql"
        query_path.write_text(
            'query Search { search(query: "mutation label", type: ISSUE, first: 1) '
            "{ issueCount } }",
            encoding="utf-8",
        )

        operations = ledger.classify_gh_operations(
            f"gh api graphql --field query=@{query_path}", "/tmp"
        )

        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].kind, "read")

    def test_dynamic_api_method_and_graphql_inputs_fail_closed(self):
        cases = (
            ("gh api -XDELETE repos/owner/repo/issues/11", "write"),
            ("gh api --method PROPFIND repos/owner/repo/issues/11", "write"),
            ("gh api -X '$METHOD' repos/owner/repo/issues/11", "unknown"),
            ("gh api graphql --field 'query=$GRAPHQL_QUERY'", "unknown"),
            ("gh api graphql --raw-field 'query=$(build_query)'", "unknown"),
            (
                "gh api graphql -F owner=owner -F name=repo -F number=11 "
                "-f 'query=$OP X { closeIssue(input:{}) { clientMutationId } }'",
                "unknown",
            ),
        )

        for command, expected in cases:
            with self.subTest(command=command):
                operations = ledger.classify_gh_operations(command, "/tmp")
                self.assertEqual(len(operations), 1)
                self.assertEqual(operations[0].kind, expected)
                if expected == "unknown":
                    self.assertFalse(operations[0].read_eligible)

    def test_nested_shell_github_writes_are_detected(self):
        commands = (
            "bash -lc 'gh pr comment 11 --repo owner/repo --body done'",
            'sh -c "gh issue edit 12 --repo owner/repo --title fixed"',
            "env zsh -lc 'gh release delete v1.0 --repo owner/repo --yes'",
            'printf "%s" "$(gh pr edit 13 --repo owner/repo --title fixed)"',
            'printf "%s" "`gh release delete v1.1 --repo owner/repo --yes`"',
            "cat <(gh pr comment 14 --repo owner/repo --body done)",
            "(gh pr edit 15 --repo owner/repo --title fixed)",
        )

        for command in commands:
            with self.subTest(command=command):
                operations = ledger.classify_gh_operations(command, "/tmp")
                self.assertEqual(len(operations), 1)
                self.assertEqual(operations[0].kind, "write")

    def test_graphql_number_targets_do_not_bridge_to_cli_prs(self):
        bound_query = Path(self.temporary.name) / "bound-pr.graphql"
        bound_query.write_text(
            "query Pull($owner:String!,$name:String!,$number:Int!) "
            "{ repository(owner:$owner,name:$name) "
            "{ pullRequest(number:$number) { state } } }",
            encoding="utf-8",
        )
        unused_fields = ledger.classify_gh_operations(
            "gh api graphql -F owner=owner -F name=repo -F number=11 "
            "-f 'query=query Viewer { viewer { login } }'",
            "/tmp",
        )[0]
        bound_fields = ledger.classify_gh_operations(
            "gh api graphql -F owner=owner -F name=repo -F number=11 "
            f"-f query=@{bound_query}",
            "/tmp",
        )[0]
        pr_write = ledger.classify_gh_operations(
            "gh pr comment 11 --repo owner/repo --body done", "/tmp"
        )[0]

        self.assertEqual(unused_fields.kind, "read")
        self.assertNotEqual(unused_fields.workflow_key, pr_write.workflow_key)
        self.assertEqual(bound_fields.kind, "read")
        self.assertNotEqual(bound_fields.workflow_key, pr_write.workflow_key)

    def test_graphql_discussion_number_is_not_a_pr_target(self):
        discussion_query = Path(self.temporary.name) / "discussion.graphql"
        discussion_query.write_text(
            "query Discussion($owner:String!,$name:String!,$number:Int!) "
            "{ repository(owner:$owner,name:$name) "
            "{ discussion(number:$number) { id } } }",
            encoding="utf-8",
        )
        discussion = ledger.classify_gh_operations(
            "gh api graphql -F owner=owner -F name=repo -F number=11 "
            f"-f query=@{discussion_query}",
            "/tmp",
        )[0]
        pr_write = ledger.classify_gh_operations(
            "gh pr comment 11 --repo owner/repo --body done", "/tmp"
        )[0]

        self.assertEqual(discussion.kind, "read")
        self.assertNotEqual(discussion.workflow_key, pr_write.workflow_key)

    def test_inline_graphql_interpolation_and_file_targets_fail_closed(self):
        query_path = Path(self.temporary.name) / "bound.graphql"
        query_path.write_text(
            "query Pull($owner:String!,$name:String!,$number:Int!) "
            "{ repository(owner:$owner,name:$name) "
            "{ pullRequest(number:$number) { state } } }",
            encoding="utf-8",
        )
        cases = (
            (
                "gh api graphql -f 'query=fragment F on Issue { id } "
                "$OP X { closeIssue(input:{}) { clientMutationId } }'",
                "unknown",
            ),
            (
                "gh api graphql -F owner=@owner.txt -F name=repo -F number=11 "
                f"-f query=@{query_path}",
                "read",
            ),
        )

        for command, expected in cases:
            with self.subTest(command=command):
                operation = ledger.classify_gh_operations(command, "/tmp")[0]
                self.assertEqual(operation.kind, expected)
                self.assertFalse(operation.read_eligible)

    def test_only_direct_success_coupled_reads_are_eligible(self):
        fakes = (
            "echo gh pr view 11 --repo owner/repo --json state",
            "true || gh pr view 11 --repo owner/repo --json state",
            "gh pr view 11 --repo owner/repo --json state || true",
        )
        write = "gh pr comment 11 --repo owner/repo --body done"

        for index, fake_read in enumerate(fakes):
            with self.subTest(fake_read=fake_read):
                state_dir = str(Path(self.state_dir) / f"fake-read-{index}")
                operations = ledger.classify_gh_operations(fake_read, "/tmp")
                if fake_read.startswith("echo "):
                    self.assertEqual(operations, [])
                else:
                    self.assertFalse(operations[0].read_eligible)
                ledger.run_hook(
                    hook_payload("PostToolUse", fake_read, {"exit_code": 0}),
                    agent="codex",
                    mode="enforce",
                    explicit_state_dir=state_dir,
                )
                denied = ledger.run_hook(
                    hook_payload("PreToolUse", write),
                    agent="codex",
                    mode="enforce",
                    explicit_state_dir=state_dir,
                )
                self.assertEqual(
                    denied["hookSpecificOutput"]["permissionDecision"], "deny"
                )

        fake_write = "echo gh pr comment 11 --repo owner/repo --body done"
        self.assertEqual(ledger.classify_gh_operations(fake_write, "/tmp"), [])
        self.assertIsNone(
            ledger.run_hook(
                hook_payload("PreToolUse", fake_write),
                agent="codex",
                mode="audit",
                explicit_state_dir=str(Path(self.state_dir) / "fake-write"),
            )
        )

        readback_state = str(Path(self.state_dir) / "fake-readback")
        direct_read = "gh pr view 11 --repo owner/repo --json state"
        ledger.run_hook(
            hook_payload("PostToolUse", direct_read, {"exit_code": 0}),
            agent="codex",
            mode="enforce",
            explicit_state_dir=readback_state,
        )
        self.assertIsNone(
            ledger.run_hook(
                hook_payload("PreToolUse", write),
                agent="codex",
                mode="enforce",
                explicit_state_dir=readback_state,
            )
        )
        ledger.run_hook(
            hook_payload("PostToolUse", write, {"exit_code": 0}),
            agent="codex",
            mode="enforce",
            explicit_state_dir=readback_state,
        )
        ledger.run_hook(
            hook_payload("PostToolUse", f"{direct_read} || true", {"exit_code": 0}),
            agent="codex",
            mode="enforce",
            explicit_state_dir=readback_state,
        )
        stop = ledger.run_hook(
            hook_payload("Stop", ""),
            agent="codex",
            mode="enforce",
            explicit_state_dir=readback_state,
        )
        self.assertEqual(stop["decision"], "block")

    def test_opaque_graphql_input_does_not_pollute_encounters(self):
        state_dir = str(Path(self.state_dir) / "opaque-graphql")
        command = (
            "printf %s 'query Pull { viewer { login } }' | gh api graphql -F query=@-"
        )
        operation = ledger.classify_gh_operations(command, "/tmp")[0]

        self.assertEqual(operation.kind, "unknown")
        self.assertFalse(operation.read_eligible)
        self.assertIsNone(
            ledger.run_hook(
                hook_payload("PreToolUse", command),
                agent="codex",
                mode="audit",
                explicit_state_dir=state_dir,
            )
        )
        ledger.run_hook(
            hook_payload("PostToolUse", command, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=state_dir,
        )
        self.assertEqual(
            ledger.run_hook(
                hook_payload("Stop", ""),
                agent="codex",
                mode="audit",
                explicit_state_dir=state_dir,
            ),
            {},
        )

    def test_environment_repo_and_host_are_part_of_exact_scope(self):
        repo_a = ledger.classify_gh_operations(
            "GH_REPO=owner/repo-a gh pr view 11 --json state", "/tmp"
        )[0]
        repo_b = ledger.classify_gh_operations(
            "GH_REPO=owner/repo-b gh pr comment 11 --body done", "/tmp"
        )[0]
        host_b = ledger.classify_gh_operations(
            "GH_REPO=owner/repo-a GH_HOST=git.example gh pr view 11 --json state",
            "/tmp",
        )[0]
        bare_after_cd = ledger.classify_gh_operations(
            "cd /tmp && gh pr view 11 --json state", "/tmp"
        )[0]
        placeholder_api = ledger.classify_gh_operations(
            "gh api repos/{owner}/{repo}/pulls/11", "/tmp"
        )[0]

        self.assertTrue(repo_a.read_eligible)
        self.assertNotEqual(repo_a.workflow_key, repo_b.workflow_key)
        self.assertNotEqual(repo_a.workflow_key, host_b.workflow_key)
        self.assertFalse(bare_after_cd.read_eligible)
        self.assertFalse(placeholder_api.read_eligible)

    def test_deeply_nested_shell_github_writes_do_not_disappear(self):
        command = "gh pr comment 11 --repo owner/repo --body done"
        for _ in range(6):
            command = f"bash -lc {shlex.quote(command)}"

        operations = ledger.classify_gh_operations(command, "/tmp")

        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].kind, "write")
        self.assertEqual(operations[0].workflow_label, "owner/repo#11")

    def test_dynamic_targets_cannot_authorize_an_exact_match(self):
        cases = (
            (
                "gh pr view '$PR_NUMBER' --repo owner/repo --json state",
                "gh pr comment '$PR_NUMBER' --repo owner/repo --body done",
            ),
            (
                "gh workflow view '${WORKFLOW}' --repo owner/repo",
                "gh workflow run '${WORKFLOW}' --repo owner/repo",
            ),
            (
                "gh pr view 11 --repo '$REPOSITORY' --json state",
                "gh pr comment 11 --repo '$REPOSITORY' --body done",
            ),
        )

        for index, (dynamic_read, dynamic_write) in enumerate(cases):
            with self.subTest(dynamic_read=dynamic_read):
                state_dir = str(Path(self.state_dir) / f"dynamic-target-{index}")
                read_operation = ledger.classify_gh_operations(dynamic_read, "/tmp")[0]
                self.assertEqual(read_operation.kind, "read")
                self.assertFalse(read_operation.read_eligible)
                ledger.run_hook(
                    hook_payload("PostToolUse", dynamic_read, {"exit_code": 0}),
                    agent="codex",
                    mode="audit",
                    explicit_state_dir=state_dir,
                )
                preflight = ledger.run_hook(
                    hook_payload("PreToolUse", dynamic_write),
                    agent="codex",
                    mode="audit",
                    explicit_state_dir=state_dir,
                )
                self.assertIn("systemMessage", preflight)

    def test_graphql_operation_name_selects_a_later_mutation(self):
        document_path = Path(self.temporary.name) / "multi-operation.graphql"
        document_path.write_text(
            """
            query Q { viewer { login } }
            mutation M { addComment(input: {}) { clientMutationId } }
            """,
            encoding="utf-8",
        )

        selected_query = ledger.classify_gh_operations(
            f"gh api graphql -f operationName=Q -f query=@{document_path}",
            "/tmp",
        )
        selected_mutation = ledger.classify_gh_operations(
            f"gh api graphql -f operationName=M -f query=@{document_path}",
            "/tmp",
        )

        self.assertEqual(selected_query[0].kind, "read")
        self.assertEqual(selected_mutation[0].kind, "write")

    def test_targeted_resources_use_exact_run_release_workflow_and_api_keys(self):
        cases = (
            (
                "gh run view 100 --repo owner/repo",
                "gh run cancel 100 --repo owner/repo",
                "gh run view 101 --repo owner/repo",
            ),
            (
                "gh release view v1.0 --repo owner/repo",
                "gh release edit v1.0 --repo owner/repo --title stable",
                "gh release view v2.0 --repo owner/repo",
            ),
            (
                "gh workflow view ci.yml --repo owner/repo",
                "gh workflow run ci.yml --repo owner/repo",
                "gh workflow view release.yml --repo owner/repo",
            ),
            (
                "gh api repos/owner/repo/actions/runs/100",
                "gh api -X DELETE repos/owner/repo/actions/runs/100",
                "gh api repos/owner/repo/actions/runs/101",
            ),
        )

        for read, write, other_read in cases:
            with self.subTest(write=write):
                read_operation = ledger.classify_gh_operations(read, "/tmp")[0]
                write_operation = ledger.classify_gh_operations(write, "/tmp")[0]
                other_operation = ledger.classify_gh_operations(other_read, "/tmp")[0]
                self.assertEqual(read_operation.kind, "read")
                self.assertEqual(write_operation.kind, "write")
                self.assertEqual(
                    read_operation.workflow_key, write_operation.workflow_key
                )
                self.assertNotEqual(
                    other_operation.workflow_key, write_operation.workflow_key
                )

    def test_audit_records_missing_preflight_and_readback(self):
        write = "gh pr review 11 --repo owner/repo --approve"
        pre = ledger.run_hook(
            hook_payload("PreToolUse", write),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIn("systemMessage", pre)

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

    def test_readback_must_match_the_exact_written_target(self):
        read_11 = "gh pr view 11 --repo owner/repo --json state"
        write_11 = "gh pr comment 11 --repo owner/repo --body done"
        read_12 = "gh pr view 12 --repo owner/repo --json state"
        ledger.run_hook(
            hook_payload("PostToolUse", read_11, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIsNone(
            ledger.run_hook(
                hook_payload("PreToolUse", write_11),
                agent="codex",
                mode="audit",
                explicit_state_dir=self.state_dir,
            )
        )
        ledger.run_hook(
            hook_payload("PostToolUse", write_11, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload("PostToolUse", read_12, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        connection = self.connection()
        try:
            pending = connection.execute(
                """
                SELECT pending_write FROM hook_activity
                WHERE workflow_label = 'owner/repo#11'
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(pending)
        self.assertEqual(pending["pending_write"], 1)

        stop = ledger.run_hook(
            hook_payload("Stop"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIn("systemMessage", stop)
        connection = self.connection()
        try:
            row = connection.execute(
                """
                SELECT outcome FROM encounters
                WHERE rule_id = 'GH-WRITE-READBACK-001'
                  AND workflow_label = 'owner/repo#11'
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row["outcome"], "escaped")

    def test_pull_requests_and_issues_with_the_same_number_are_distinct(self):
        pr_read = ledger.classify_gh_operations(
            "gh pr view 11 --repo owner/repo --json state", "/tmp"
        )[0]
        pr_write = ledger.classify_gh_operations(
            "gh pr comment 11 --repo owner/repo --body done", "/tmp"
        )[0]
        issue_read = ledger.classify_gh_operations(
            "gh issue view 11 --repo owner/repo --json state", "/tmp"
        )[0]
        pull_rest = ledger.classify_gh_operations(
            "gh api repos/owner/repo/pulls/11", "/tmp"
        )[0]
        ambiguous_issue_rest = ledger.classify_gh_operations(
            "gh api repos/owner/repo/issues/11", "/tmp"
        )[0]

        self.assertEqual(pr_read.workflow_key, pr_write.workflow_key)
        self.assertEqual(pull_rest.workflow_key, pr_write.workflow_key)
        self.assertNotEqual(issue_read.workflow_key, pr_write.workflow_key)
        self.assertNotEqual(ambiguous_issue_rest.workflow_key, pr_write.workflow_key)
        self.assertNotEqual(ambiguous_issue_rest.workflow_key, issue_read.workflow_key)

    def test_failed_read_does_not_satisfy_preflight(self):
        read = "gh pr view 11 --repo owner/repo --json state"
        write = "gh pr comment 11 --repo owner/repo --body done"
        ledger.run_hook(
            hook_payload("PostToolUse", read, {"exit_code": 1}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        result = ledger.run_hook(
            hook_payload("PreToolUse", write),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIn("systemMessage", result)

    def test_alternate_failure_shapes_do_not_satisfy_preflight(self):
        read = "gh pr view 11 --repo owner/repo --json state"
        write = "gh pr comment 11 --repo owner/repo --body done"
        failure_shapes = (
            {"exitCode": 3},
            {"result": {"status": "failed"}},
            {"result": {"ok": False}},
            {"metadata": {"is_error": True}},
            "Process exited with code 9",
        )

        for index, response in enumerate(failure_shapes):
            with self.subTest(response=response):
                state_dir = str(Path(self.state_dir) / f"failure-{index}")
                ledger.run_hook(
                    hook_payload("PostToolUse", read, response),
                    agent="codex",
                    mode="audit",
                    explicit_state_dir=state_dir,
                )
                result = ledger.run_hook(
                    hook_payload("PreToolUse", write),
                    agent="codex",
                    mode="audit",
                    explicit_state_dir=state_dir,
                )
                self.assertIn("systemMessage", result)

    def test_failed_write_resets_preflight_and_remains_pending(self):
        read = "gh pr view 11 --repo owner/repo --json state"
        write = "gh pr comment 11 --repo owner/repo --body done"
        ledger.run_hook(
            hook_payload("PostToolUse", read, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIsNone(
            ledger.run_hook(
                hook_payload("PreToolUse", write),
                agent="codex",
                mode="audit",
                explicit_state_dir=self.state_dir,
            )
        )
        ledger.run_hook(
            hook_payload("PostToolUse", write, {"exit_code": 1}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        second_preflight = ledger.run_hook(
            hook_payload("PreToolUse", write),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIn("systemMessage", second_preflight)
        stop = ledger.run_hook(
            hook_payload("Stop"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIn("systemMessage", stop)

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
        self.assertIn("systemMessage", result)

    def test_pr_list_numeric_flags_do_not_authorize_a_numbered_pr_write(self):
        listing = "gh pr list --repo owner/repo --limit 11"
        write = "gh pr comment 11 --repo owner/repo --body done"
        ledger.run_hook(
            hook_payload("PostToolUse", listing, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        result = ledger.run_hook(
            hook_payload("PreToolUse", write),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        self.assertIn("systemMessage", result)

    def test_allowed_pre_without_post_remains_pending_until_stop(self):
        read = "gh pr view 11 --repo owner/repo --json state"
        write = "gh pr comment 11 --repo owner/repo --body done"
        ledger.run_hook(
            hook_payload("PostToolUse", read, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIsNone(
            ledger.run_hook(
                hook_payload("PreToolUse", write),
                agent="codex",
                mode="audit",
                explicit_state_dir=self.state_dir,
            )
        )

        connection = self.connection()
        try:
            pending = connection.execute(
                "SELECT COUNT(*) FROM hook_activity WHERE pending_write = 1"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(pending, 1)
        stop = ledger.run_hook(
            hook_payload("Stop"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIn("systemMessage", stop)

    def test_legacy_raw_hook_ids_are_not_orphaned_after_upgrade(self):
        legacy_session_id = "legacy-session-id"
        write = "gh pr comment 61 --repo owner/repo --body done"
        operation = ledger.classify_gh_operations(write, "/tmp")[0]
        connection = self.connection()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO hook_activity (
                        session_id, turn_id, workflow_key, workflow_label,
                        repo_key, preflight_seen, pending_write,
                        pending_summary, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?)
                    """,
                    (
                        legacy_session_id,
                        "legacy-turn-id",
                        operation.workflow_key,
                        operation.workflow_label,
                        operation.repo_key,
                        operation.summary,
                        ledger.isoformat(ledger.utc_now()),
                    ),
                )
        finally:
            connection.close()

        ledger.run_hook(
            {
                "session_id": legacy_session_id,
                "cwd": "/tmp",
                "hook_event_name": "SessionStart",
                "source": "resume",
            },
            agent="claude",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        connection = self.connection()
        try:
            legacy_rows = connection.execute(
                "SELECT COUNT(*) FROM hook_activity WHERE session_id = ?",
                (legacy_session_id,),
            ).fetchone()[0]
            escaped = connection.execute(
                """
                SELECT COUNT(*) FROM encounters
                WHERE rule_id = 'GH-WRITE-READBACK-001'
                  AND workflow_label = ? AND outcome = 'escaped'
                """,
                (operation.workflow_label,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(legacy_rows, 0)
        self.assertEqual(escaped, 1)

    def test_codex_recovers_pending_state_when_the_next_turn_has_a_new_id(self):
        read = "gh pr view 62 --repo owner/repo --json state"
        write = "gh pr comment 62 --repo owner/repo --body done"
        for event, command, response in (
            ("PostToolUse", read, {"exit_code": 0}),
            ("PreToolUse", write, None),
            ("PostToolUse", write, {"exit_code": 0}),
        ):
            ledger.run_hook(
                hook_payload(event, command, response, turn_id="turn-before-gap"),
                agent="codex",
                mode="audit",
                explicit_state_dir=self.state_dir,
            )

        # The old turn's Stop never arrived. A complete later turn still has to
        # recover that pending write rather than leaving it unreachable forever.
        ledger.run_hook(
            hook_payload(
                "PreToolUse",
                "gh pr view 99 --repo owner/repo --json state",
                turn_id="turn-after-gap",
            ),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload("Stop", turn_id="turn-after-gap"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        connection = self.connection()
        try:
            pending = connection.execute(
                """
                SELECT COUNT(*) FROM hook_activity
                WHERE session_id = ? AND pending_write = 1
                """,
                (ledger._runtime_id("session", "session-1"),),
            ).fetchone()[0]
            escaped = connection.execute(
                """
                SELECT COUNT(*) FROM encounters
                WHERE rule_id = 'GH-WRITE-READBACK-001'
                  AND workflow_label = 'owner/repo#62' AND outcome = 'escaped'
                """
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(pending, 0)
        self.assertEqual(escaped, 1)

    def test_enforcement_denial_has_no_post_and_stop_keeps_blocking_pending(self):
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
        no_pending_stop = ledger.run_hook(
            hook_payload("Stop"),
            agent="codex",
            mode="enforce",
            explicit_state_dir=self.state_dir,
        )
        self.assertEqual(no_pending_stop, {})

        read = "gh issue view 12 --repo owner/repo --json state"
        ledger.run_hook(
            hook_payload("PostToolUse", read, {"exit_code": 0}),
            agent="codex",
            mode="enforce",
            explicit_state_dir=self.state_dir,
        )
        self.assertIsNone(
            ledger.run_hook(
                hook_payload("PreToolUse", write),
                agent="codex",
                mode="enforce",
                explicit_state_dir=self.state_dir,
            )
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
        self.assertEqual(final_stop["decision"], "block")

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
        self.assertEqual(len(owned), 5)
        self.assertIn("'/opt/secquoia/encounter ledger.py'", owned[0]["command"])
        owned_groups = {
            event: group
            for event, groups in document["hooks"].items()
            for group in groups
            if any(
                ledger.INSTALLATION_ID in handler.get("command", "")
                for handler in group["hooks"]
            )
        }
        self.assertEqual(
            set(owned_groups),
            {"PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "Stop"},
        )
        self.assertEqual(
            owned_groups["SessionStart"]["matcher"], "startup|resume|clear"
        )
        for event in ("UserPromptSubmit", "Stop"):
            self.assertNotIn("matcher", owned_groups[event])

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

    def run_successful_command(
        self,
        command: str,
        *,
        session_id: str,
        tool_use_id: str,
        agent_id: str | None = None,
    ) -> None:
        extra = {"agent_id": agent_id} if agent_id else {}
        self.assertIsNone(
            self.run_hook(
                claude_payload(
                    "PreToolUse",
                    command,
                    session_id=session_id,
                    tool_use_id=tool_use_id,
                    **extra,
                )
            )
        )
        self.run_hook(
            claude_payload(
                "PostToolUse",
                command,
                CLAUDE_BASH_OK,
                session_id=session_id,
                tool_use_id=tool_use_id,
                **extra,
            )
        )

    def prepare_pending_write(
        self,
        *,
        session_id: str,
        number: int,
        agent_id: str | None = None,
    ) -> str:
        read = f"gh pr view {number} --repo owner/repo --json state"
        write = f"gh pr comment {number} --repo owner/repo --body done"
        extra = {"agent_id": agent_id} if agent_id else {}
        self.run_successful_command(
            read,
            session_id=session_id,
            tool_use_id=f"toolu_read_{number}",
            agent_id=agent_id,
        )
        self.assertIsNone(
            self.run_hook(
                claude_payload(
                    "PreToolUse",
                    write,
                    session_id=session_id,
                    tool_use_id=f"toolu_write_{number}",
                    **extra,
                )
            )
        )
        self.run_hook(
            claude_payload(
                "PostToolUse",
                write,
                CLAUDE_BASH_OK,
                session_id=session_id,
                tool_use_id=f"toolu_write_{number}",
                **extra,
            )
        )
        return write

    def assert_session_activity_cleared(self, session_id: str) -> None:
        connection = ledger.connect_database(self.state_dir)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM hook_activity WHERE session_id = ?",
                (ledger._runtime_id("session", session_id),),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 0)

    def assert_readback_escaped(self, workflow_label: str) -> None:
        connection = ledger.connect_database(self.state_dir)
        try:
            row = connection.execute(
                """
                SELECT outcome FROM encounters
                WHERE rule_id = 'GH-WRITE-READBACK-001'
                  AND workflow_label = ?
                """,
                (workflow_label,),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["outcome"], "escaped")

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
        session_id = "claude-successful-flow"
        read = "gh pr view 11 --repo owner/repo --json state"
        write = "gh pr comment 11 --repo owner/repo --body done"
        self.run_successful_command(
            read,
            session_id=session_id,
            tool_use_id="toolu_successful_read_before",
        )
        self.assertIsNone(
            self.run_hook(
                claude_payload(
                    "PreToolUse",
                    write,
                    session_id=session_id,
                    tool_use_id="toolu_successful_write",
                )
            )
        )
        self.run_hook(
            claude_payload(
                "PostToolUse",
                write,
                CLAUDE_BASH_OK,
                session_id=session_id,
                tool_use_id="toolu_successful_write",
            )
        )
        self.run_successful_command(
            read,
            session_id=session_id,
            tool_use_id="toolu_successful_read_after",
        )
        stop = self.run_hook(
            claude_payload("Stop", session_id=session_id, stop_hook_active=False)
        )
        self.assertEqual(stop, {})

    def test_claude_interrupted_write_is_pending_but_not_counted_as_success(self):
        session_id = "claude-interrupted-write"
        read = "gh pr view 11 --repo owner/repo --json state"
        write = "gh pr comment 11 --repo owner/repo --body done"
        self.run_successful_command(
            read,
            session_id=session_id,
            tool_use_id="toolu_interrupted_read",
        )
        self.assertIsNone(
            self.run_hook(
                claude_payload(
                    "PreToolUse",
                    write,
                    session_id=session_id,
                    tool_use_id="toolu_interrupted_write",
                )
            )
        )
        interrupted = dict(CLAUDE_BASH_OK, interrupted=True)
        self.run_hook(
            claude_payload(
                "PostToolUse",
                write,
                interrupted,
                session_id=session_id,
                tool_use_id="toolu_interrupted_write",
            )
        )

        connection = ledger.connect_database(self.state_dir)
        try:
            pending = connection.execute(
                "SELECT COUNT(*) FROM hook_activity WHERE pending_write = 1"
            ).fetchone()[0]
            passed_readbacks = connection.execute(
                """
                SELECT COUNT(*) FROM encounters
                WHERE rule_id = 'GH-WRITE-READBACK-001' AND outcome = 'passed'
                """
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(pending, 1)
        self.assertEqual(passed_readbacks, 0)
        next_preflight = self.run_hook(
            claude_payload(
                "PreToolUse",
                write,
                session_id=session_id,
                tool_use_id="toolu_interrupted_retry",
            )
        )
        self.assertIn("additionalContext", next_preflight["hookSpecificOutput"])

    def test_claude_post_tool_failure_tracks_ambiguous_write(self):
        session_id = "claude-failed-write"
        read = "gh pr view 13 --repo owner/repo --json state"
        write = "gh pr comment 13 --repo owner/repo --body done"
        self.run_successful_command(
            read,
            session_id=session_id,
            tool_use_id="toolu_failed_read_setup",
        )
        self.assertIsNone(
            self.run_hook(
                claude_payload(
                    "PreToolUse",
                    write,
                    session_id=session_id,
                    tool_use_id="toolu_failed_write",
                )
            )
        )
        self.run_hook(
            claude_payload(
                "PostToolUseFailure",
                write,
                session_id=session_id,
                tool_use_id="toolu_failed_write",
                error="network connection closed",
                is_interrupt=False,
            )
        )

        connection = ledger.connect_database(self.state_dir)
        try:
            pending = connection.execute(
                """
                SELECT pending_write, preflight_seen FROM hook_activity
                WHERE session_id = ? AND workflow_label = 'owner/repo#13'
                """,
                (ledger._runtime_id("session", session_id),),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(pending)
        self.assertEqual(pending["pending_write"], 1)
        self.assertEqual(pending["preflight_seen"], 0)

    def test_claude_post_tool_failure_does_not_create_a_preflight(self):
        session_id = "claude-failed-read"
        read = "gh pr view 14 --repo owner/repo --json state"
        write = "gh pr comment 14 --repo owner/repo --body done"
        self.assertIsNone(
            self.run_hook(
                claude_payload(
                    "PreToolUse",
                    read,
                    session_id=session_id,
                    tool_use_id="toolu_failed_read",
                )
            )
        )
        self.run_hook(
            claude_payload(
                "PostToolUseFailure",
                read,
                session_id=session_id,
                tool_use_id="toolu_failed_read",
                error="command failed",
                is_interrupt=False,
            )
        )

        result = self.run_hook(
            claude_payload(
                "PreToolUse",
                write,
                session_id=session_id,
                tool_use_id="toolu_after_failed_read",
            )
        )
        self.assertIn("additionalContext", result["hookSpecificOutput"])

    def test_user_prompt_submit_finalizes_and_clears_the_previous_turn(self):
        session_id = "claude-user-prompt-boundary"
        write = self.prepare_pending_write(session_id=session_id, number=21)

        boundary = self.run_hook(
            claude_payload("UserPromptSubmit", session_id=session_id)
        )
        self.assertIn("additionalContext", boundary["hookSpecificOutput"])
        self.assert_session_activity_cleared(session_id)
        self.assert_readback_escaped("owner/repo#21")
        next_preflight = self.run_hook(
            claude_payload(
                "PreToolUse",
                write,
                session_id=session_id,
                tool_use_id="toolu_new_prompt_write",
            )
        )
        self.assertIn("additionalContext", next_preflight["hookSpecificOutput"])

    def test_session_start_finalizes_and_clears_stale_activity(self):
        session_id = "claude-resumed-session"
        write = self.prepare_pending_write(session_id=session_id, number=22)

        boundary = self.run_hook(
            claude_payload("SessionStart", session_id=session_id, source="resume")
        )
        self.assertIn("additionalContext", boundary["hookSpecificOutput"])
        self.assert_session_activity_cleared(session_id)
        self.assert_readback_escaped("owner/repo#22")
        next_preflight = self.run_hook(
            claude_payload(
                "PreToolUse",
                write,
                session_id=session_id,
                tool_use_id="toolu_resumed_write",
            )
        )
        self.assertIn("additionalContext", next_preflight["hookSpecificOutput"])

    def test_session_start_compact_preserves_current_turn_state(self):
        session_id = "claude-compact-session"
        self.prepare_pending_write(session_id=session_id, number=26)

        boundary = self.run_hook(
            claude_payload("SessionStart", session_id=session_id, source="compact")
        )

        self.assertIsNone(boundary)
        connection = ledger.connect_database(self.state_dir)
        try:
            pending = connection.execute(
                """
                SELECT COUNT(*) FROM hook_activity
                WHERE session_id = ? AND pending_write = 1
                """,
                (ledger._runtime_id("session", session_id),),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(pending, 1)
        stop = self.run_hook(claude_payload("Stop", session_id=session_id))
        self.assertIn("systemMessage", stop)

    def test_agent_ids_have_isolated_preflight_state(self):
        session_id = "claude-agent-isolation"
        read = "gh pr view 27 --repo owner/repo --json state"
        write = "gh pr comment 27 --repo owner/repo --body done"
        self.run_successful_command(
            read,
            session_id=session_id,
            tool_use_id="toolu_agent_a_read",
            agent_id="agent-a",
        )

        result = self.run_hook(
            claude_payload(
                "PreToolUse",
                write,
                session_id=session_id,
                tool_use_id="toolu_agent_b_write",
                agent_id="agent-b",
            )
        )

        self.assertIn("additionalContext", result["hookSpecificOutput"])

    def test_subagent_stop_cleans_only_that_agents_pending_state(self):
        session_id = "claude-subagent-stop"
        self.prepare_pending_write(session_id=session_id, number=28)
        self.prepare_pending_write(
            session_id=session_id,
            number=29,
            agent_id="worker-1",
        )

        stopped = self.run_hook(
            claude_payload(
                "SubagentStop",
                session_id=session_id,
                agent_id="worker-1",
                stop_hook_active=False,
            )
        )

        self.assertIn("systemMessage", stopped)
        connection = ledger.connect_database(self.state_dir)
        try:
            pending_labels = {
                row["workflow_label"]
                for row in connection.execute(
                    """
                    SELECT workflow_label FROM hook_activity
                    WHERE session_id = ? AND pending_write = 1
                    """,
                    (ledger._runtime_id("session", session_id),),
                ).fetchall()
            }
        finally:
            connection.close()
        self.assertEqual(pending_labels, {"owner/repo#28"})
        self.assert_readback_escaped("owner/repo#29")

        root_stop = self.run_hook(claude_payload("Stop", session_id=session_id))
        self.assertIn("systemMessage", root_stop)

    def test_stop_failure_and_session_end_finalize_without_output(self):
        cases = (
            (
                "StopFailure",
                "claude-stop-failure",
                23,
                {"error": "rate_limit", "last_assistant_message": ""},
            ),
            (
                "SessionEnd",
                "claude-session-end",
                24,
                {"reason": "other"},
            ),
        )
        for event, session_id, number, extra in cases:
            with self.subTest(event=event):
                write = self.prepare_pending_write(session_id=session_id, number=number)
                boundary = self.run_hook(
                    claude_payload(event, session_id=session_id, **extra)
                )
                self.assertFalse(boundary)
                self.assert_session_activity_cleared(session_id)
                self.assert_readback_escaped(f"owner/repo#{number}")
                next_preflight = self.run_hook(
                    claude_payload(
                        "PreToolUse",
                        write,
                        session_id=session_id,
                        tool_use_id=f"toolu_after_{event}",
                    )
                )
                self.assertIn("additionalContext", next_preflight["hookSpecificOutput"])

    def test_late_old_tool_result_cannot_authorize_the_new_prompt(self):
        session_id = "claude-late-tool-result"
        read = "gh pr view 25 --repo owner/repo --json state"
        write = "gh pr comment 25 --repo owner/repo --body done"
        self.run_hook(claude_payload("UserPromptSubmit", session_id=session_id))
        self.run_hook(
            claude_payload(
                "PreToolUse",
                read,
                session_id=session_id,
                tool_use_id="toolu_old_read",
            )
        )

        self.run_hook(claude_payload("UserPromptSubmit", session_id=session_id))
        self.run_hook(
            claude_payload(
                "PostToolUse",
                read,
                CLAUDE_BASH_OK,
                session_id=session_id,
                tool_use_id="toolu_old_read",
            )
        )
        result = self.run_hook(
            claude_payload(
                "PreToolUse",
                write,
                session_id=session_id,
                tool_use_id="toolu_new_write",
            )
        )

        self.assertIn("additionalContext", result["hookSpecificOutput"])

    def test_concurrent_boundary_and_old_post_cannot_silently_drop_pending_state(
        self,
    ):
        for index in range(4):
            with self.subTest(index=index):
                session_id = f"claude-concurrent-boundary-{index}"
                number = 40 + index
                read = f"gh pr view {number} --repo owner/repo --json state"
                write = f"gh pr comment {number} --repo owner/repo --body done"
                write_tool_id = f"toolu_concurrent_write_{index}"
                self.run_successful_command(
                    read,
                    session_id=session_id,
                    tool_use_id=f"toolu_concurrent_read_{index}",
                )
                self.assertIsNone(
                    self.run_hook(
                        claude_payload(
                            "PreToolUse",
                            write,
                            session_id=session_id,
                            tool_use_id=write_tool_id,
                        )
                    )
                )

                barrier = threading.Barrier(2)

                def submit_boundary():
                    barrier.wait(timeout=5)
                    return self.run_hook(
                        claude_payload("UserPromptSubmit", session_id=session_id)
                    )

                def submit_post():
                    barrier.wait(timeout=5)
                    return self.run_hook(
                        claude_payload(
                            "PostToolUse",
                            write,
                            CLAUDE_BASH_OK,
                            session_id=session_id,
                            tool_use_id=write_tool_id,
                        )
                    )

                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [
                        executor.submit(submit_boundary),
                        executor.submit(submit_post),
                    ]
                    for future in futures:
                        future.result(timeout=10)

                connection = ledger.connect_database(self.state_dir)
                try:
                    pending = connection.execute(
                        """
                        SELECT COUNT(*) FROM hook_activity
                        WHERE session_id = ? AND workflow_label = ?
                          AND pending_write = 1
                        """,
                        (
                            ledger._runtime_id("session", session_id),
                            f"owner/repo#{number}",
                        ),
                    ).fetchone()[0]
                    escaped = connection.execute(
                        """
                        SELECT COUNT(*) FROM encounters
                        WHERE rule_id = 'GH-WRITE-READBACK-001'
                          AND workflow_label = ? AND outcome = 'escaped'
                        """,
                        (f"owner/repo#{number}",),
                    ).fetchone()[0]
                finally:
                    connection.close()
                self.assertTrue(
                    pending or escaped,
                    "the boundary/Post race silently discarded the pending write",
                )

    def test_claude_enforcement_denial_has_no_post_and_stop_keeps_blocking(self):
        session_id = "claude-enforcement"
        write = "gh issue comment 12 --repo owner/repo --body done"
        denied = self.run_hook(
            claude_payload(
                "PreToolUse",
                write,
                session_id=session_id,
                tool_use_id="toolu_denied_write",
            ),
            mode="enforce",
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            self.run_hook(
                claude_payload("Stop", session_id=session_id), mode="enforce"
            ),
            {},
        )

        read = "gh issue view 12 --repo owner/repo --json state"
        self.run_successful_command(
            read,
            session_id=session_id,
            tool_use_id="toolu_enforcement_read",
        )
        self.assertIsNone(
            self.run_hook(
                claude_payload(
                    "PreToolUse",
                    write,
                    session_id=session_id,
                    tool_use_id="toolu_allowed_write",
                ),
                mode="enforce",
            )
        )
        stop = self.run_hook(
            claude_payload("Stop", session_id=session_id, stop_hook_active=False),
            mode="enforce",
        )
        self.assertEqual(stop["decision"], "block")
        reentry = self.run_hook(
            claude_payload("Stop", session_id=session_id, stop_hook_active=True),
            mode="enforce",
        )
        self.assertEqual(reentry["decision"], "block")

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
        self.assertEqual(len(owned), 9)
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
        expected_matchers = {
            "PreToolUse": "Bash",
            "PostToolUse": "Bash",
            "PostToolUseFailure": "Bash",
            "UserPromptSubmit": None,
            "Stop": None,
            "SubagentStop": None,
            "StopFailure": None,
            "SessionEnd": None,
            "SessionStart": "startup|resume|clear|fork",
        }
        owned_groups = {}
        for event, groups in document["hooks"].items():
            for group in groups:
                if any(
                    ledger.INSTALLATION_ID in handler.get("command", "")
                    for handler in group["hooks"]
                ):
                    owned_groups[event] = group
        self.assertEqual(set(owned_groups), set(expected_matchers))
        for event, matcher in expected_matchers.items():
            with self.subTest(event=event):
                if matcher is None:
                    self.assertNotIn("matcher", owned_groups[event])
                else:
                    self.assertEqual(owned_groups[event]["matcher"], matcher)

    def test_install_creates_settings_file_when_missing(self):
        path, backup = ledger.install_claude_hooks(
            self.settings_path, Path("/opt/ledger.py"), "audit"
        )
        self.assertIsNone(backup)
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(self.owned_handlers(document)), 9)

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
        self.assertEqual(set(document["hooks"]), {"PreToolUse"})
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
