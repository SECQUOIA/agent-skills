from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import shlex
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


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

    @unittest.skipIf(
        os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        "non-root POSIX permissions are required",
    )
    def test_report_command_reads_a_nonwritable_existing_ledger(self):
        now = datetime.now(timezone.utc)
        connection = self.connection()
        try:
            for offset in (50, 25, 0):
                ledger.record_encounter(
                    connection,
                    rule_id="GH-WRITE-READBACK-001",
                    workflow_id="github:o/r:number:11",
                    workflow_label="o/r#11",
                    agent="codex",
                    outcome="escaped",
                    revision="aaa",
                    now=now - timedelta(hours=offset),
                )
        finally:
            connection.close()

        state_dir = Path(self.state_dir)
        database = state_dir / "encounters.sqlite3"
        try:
            database.chmod(0o400)
            state_dir.chmod(0o500)
            output = io.StringIO()
            args = argparse.Namespace(
                state_dir=self.state_dir,
                since_days=30,
                min_encounters=3,
                json=True,
            )
            with contextlib.redirect_stdout(output):
                result = ledger._command_report(args)
        finally:
            state_dir.chmod(0o700)
            database.chmod(0o600)

        self.assertEqual(result, 0)
        rows = json.loads(output.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["violations"], 3)

    def test_report_command_does_not_create_a_missing_state_directory(self):
        state_dir = Path(self.state_dir) / "missing"
        output = io.StringIO()
        args = argparse.Namespace(
            state_dir=str(state_dir),
            since_days=30,
            min_encounters=3,
            json=True,
        )

        with contextlib.redirect_stdout(output):
            result = ledger._command_report(args)

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue()), [])
        self.assertFalse(state_dir.exists())

    def test_report_command_reads_committed_rows_from_an_active_wal(self):
        writer = self.connection()
        try:
            ledger.record_encounter(
                writer,
                rule_id="GH-WRITE-READBACK-001",
                workflow_id="github:o/r:number:11",
                workflow_label="o/r#11",
                agent="codex",
                outcome="escaped",
                revision="aaa",
            )
            args = argparse.Namespace(
                state_dir=self.state_dir,
                since_days=30,
                min_encounters=1,
                json=True,
            )
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                result = ledger._command_report(args)
        finally:
            writer.close()

        self.assertEqual(result, 0)
        rows = json.loads(output.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["violations"], 1)

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
            "bash --noprofile -c 'gh pr comment 11 --repo owner/repo --body done'",
            "bash -o pipefail -c 'gh pr comment 11 --repo owner/repo --body done'",
            "if bash -c 'gh pr comment 11 --repo owner/repo --body done'; then :; fi",
            "! bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "time bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "time -p bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "case x in x) bash -c 'gh pr comment 11 --repo owner/repo --body done' ;; esac",
            "case x in x)bash -c 'gh pr comment 11 --repo owner/repo --body done' ;; esac",
            "case x in x|y) bash -c 'gh pr comment 11 --repo owner/repo --body done' ;; esac",
            "case x in x) time bash -c 'gh pr comment 11 --repo owner/repo --body done' ;; esac",
            "{ bash -c 'gh pr comment 11 --repo owner/repo --body done'; }",
            "{ time bash -c 'gh pr comment 11 --repo owner/repo --body done'; }",
            "{ ! bash -c 'gh pr comment 11 --repo owner/repo --body done'; }",
            "NOTE='two words' bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "env 'NOTE=two words' bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "env NOTE\\=two bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "NOTE=two env -i EXTRA=three bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "env -uNOTE bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "env -C/tmp bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "NOTE=two command -p bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "command -p -- bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "NOTE=two exec -l bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "exec -c -- bash -c 'gh pr comment 11 --repo owner/repo --body done'",
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

        for harmless in (
            "echo bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "echo '(' bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "echo ')' bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "echo '{' bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "'case' x in x) bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "'{' bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "'NOTE=two words' bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "NOTE\\=two bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "NO''TE=two bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "env NOTE=two echo bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "command -v bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "command -- -p bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "exec -a bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "exec -a bash echo bash -c 'gh pr comment 11 --repo owner/repo --body done'",
            "exec -- -c bash -c 'gh pr comment 11 --repo owner/repo --body done'",
        ):
            with self.subTest(harmless=harmless):
                self.assertEqual(ledger.classify_gh_operations(harmless, "/tmp"), [])

    def test_exec_through_wrappers_expose_shell_wrapped_writes(self):
        write = "gh pr comment 11 --repo owner/repo --body done"
        for command in (
            f"timeout 5 bash -c '{write}'",
            f"timeout -k 3 300 bash -c '{write}'",
            f"xargs -0 bash -c '{write}'",
            f"xargs -I{{}} bash -c '{write}'",
            f"nice -n 10 bash -c '{write}'",
            f"nice -10 bash -c '{write}'",
            f"nohup bash -c '{write}'",
            f"stdbuf -oL bash -c '{write}'",
            f"sudo -u deploy bash -c '{write}'",
            f"env A=B timeout 5 bash -c '{write}'",
            f"A=B sudo -u deploy timeout 5 bash -c '{write}'",
        ):
            with self.subTest(command=command):
                operations = ledger.classify_gh_operations(command, "/tmp")
                self.assertEqual([op.kind for op in operations], ["write"])
                self.assertEqual(operations[0].workflow_label, "owner/repo#11")

        # Quoting a command name does not change what executes.
        quoted = f"'timeout' 5 bash -c '{write}'"
        self.assertEqual(
            [op.kind for op in ledger.classify_gh_operations(quoted, "/tmp")],
            ["write"],
        )

        for harmless in (
            f"echo timeout 5 bash -c '{write}'",
            f"timeout bash -c '{write}'",
        ):
            with self.subTest(harmless=harmless):
                self.assertEqual(ledger.classify_gh_operations(harmless, "/tmp"), [])

    def test_exec_through_wrappers_expose_direct_gh_operations(self):
        for command, expected in (
            ("timeout 300 gh pr comment 11 --repo owner/repo --body done", "write"),
            ("sudo -u deploy gh pr merge 11 --repo owner/repo", "write"),
            ("nice -n 10 gh pr view 11 --repo owner/repo --json state", "read"),
            ("stdbuf -oL gh run view 12345 --repo owner/repo", "read"),
        ):
            with self.subTest(command=command):
                operations = ledger.classify_gh_operations(command, "/tmp")
                self.assertEqual([op.kind for op in operations], [expected])

        read = "timeout 5 gh pr view 11 --repo owner/repo --json state"
        self.assertTrue(ledger.classify_gh_operations(read, "/tmp")[0].read_eligible)

        env_read = "GH_REPO=owner/repo timeout 5 gh pr view 11 --json state"
        operation = ledger.classify_gh_operations(env_read, "/tmp")[0]
        self.assertEqual(operation.workflow_label, "owner/repo#11")

        # xargs appends stdin-derived arguments, so the visible direct command
        # is incomplete and must stay untracked.
        self.assertEqual(
            ledger.classify_gh_operations(
                "xargs gh pr comment 11 --repo owner/repo --body done", "/tmp"
            ),
            [],
        )

    def test_exec_wrapper_reads_must_be_success_coupled(self):
        detached_read = "setsid -f gh pr view 11 --repo owner/repo --json state"
        waited_read = "setsid -f -w gh pr view 11 --repo owner/repo --json state"
        clustered_waited_read = (
            "setsid -fw gh pr view 11 --repo owner/repo --json state"
        )
        background_read = (
            "sudo --background gh pr view 11 --repo owner/repo --json state"
        )
        split_read = "env -S 'gh pr view 11 --repo owner/repo --json state'"
        background_split_read = f"{split_read} &"
        write = "gh pr comment 11 --repo owner/repo --body done"

        detached = ledger.classify_gh_operations(detached_read, "/tmp")[0]
        waited = ledger.classify_gh_operations(waited_read, "/tmp")[0]
        clustered_waited = ledger.classify_gh_operations(clustered_waited_read, "/tmp")[
            0
        ]
        background = ledger.classify_gh_operations(background_read, "/tmp")[0]
        split = ledger.classify_gh_operations(split_read, "/tmp")[0]
        background_split = ledger.classify_gh_operations(background_split_read, "/tmp")[
            0
        ]
        self.assertEqual(detached.kind, "read")
        self.assertFalse(detached.read_eligible)
        self.assertTrue(waited.read_eligible)
        self.assertTrue(clustered_waited.read_eligible)
        self.assertFalse(background.read_eligible)
        self.assertTrue(split.read_eligible)
        self.assertFalse(background_split.read_eligible)

        ledger.run_hook(
            hook_payload("PostToolUse", detached_read, {"exit_code": 0}),
            agent="codex",
            mode="enforce",
            explicit_state_dir=self.state_dir,
        )
        denied = ledger.run_hook(
            hook_payload("PreToolUse", write),
            agent="codex",
            mode="enforce",
            explicit_state_dir=self.state_dir,
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_exec_wrapper_grammar_recognizes_valid_chains(self):
        write = "gh pr comment 11 --repo owner/repo --body done"
        for command in (
            "sudo --user deploy gh pr merge 11 --repo owner/repo",
            "sudo -nu deploy gh pr merge 11 --repo owner/repo",
            "sudo --user gh gh pr comment 11 --repo owner/repo --body done",
            "sudo GH_REPO=owner/repo gh pr comment 11 --body done",
            "sudo --group staff gh pr merge 11 --repo owner/repo",
            "sudo --chdir /tmp gh pr merge 11 --repo owner/repo",
            "timeout 5 env gh pr comment 11 --repo owner/repo --body done",
            "env --unset gh gh pr comment 11 --repo owner/repo --body done",
            "env --list-signal-handling gh pr comment 11 --repo owner/repo --body done",
            "env -S 'gh pr comment 11 --repo owner/repo --body done'",
            "env -S '-i GH_REPO=owner/repo gh pr comment 11 --body done'",
            "env -iS 'GH_REPO=owner/repo gh pr comment 11 --body done'",
            "env -S '' gh pr comment 11 --repo owner/repo --body done",
            f"xargs -0r bash -c '{write}'",
            f"xargs -0I{{}} bash -c '{write}'",
            f"xargs --max-lines bash -c '{write}'",
            "timeout 1e-3 gh pr comment 11 --repo owner/repo --body done",
            "timeout infinity gh pr comment 11 --repo owner/repo --body done",
            "stdbuf -o1k gh pr comment 11 --repo owner/repo --body done",
            f"timeout 5 env A=B bash -c '{write}'",
        ):
            with self.subTest(command=command):
                operations = ledger.classify_gh_operations(command, "/tmp")
                self.assertEqual(
                    [operation.kind for operation in operations], ["write"]
                )
                self.assertEqual(operations[0].workflow_label, "owner/repo#11")

    def test_exec_wrapper_environment_effects_do_not_reuse_stale_scope(self):
        with mock.patch.object(ledger, "_repo_from_cwd", return_value="source/repo"):
            unset_repo = ledger.classify_gh_operations(
                "GH_REPO=wrong/repo env -u GH_REPO gh pr view 11 --json state",
                "/source",
            )[0]
            changed_cwd = ledger.classify_gh_operations(
                "env --chdir /other gh pr comment 11 --body done", "/source"
            )[0]
            sudo_changed_cwd = ledger.classify_gh_operations(
                "sudo --chdir /other gh pr comment 11 --body done", "/source"
            )[0]
            sudo_login = ledger.classify_gh_operations(
                "sudo --login gh pr comment 11 --body done", "/source"
            )[0]
            nested_changed_cwd = ledger.classify_gh_operations(
                "env --chdir /other bash -c 'gh pr comment 11 --body done'",
                "/source",
            )[0]
            reset_by_sudo = ledger.classify_gh_operations(
                "GH_REPO=wrong/repo sudo gh pr view 11 --json state", "/source"
            )[0]
            preserved_by_sudo = ledger.classify_gh_operations(
                "GH_REPO=owner/repo sudo -E gh pr view 11 --json state", "/source"
            )[0]

        self.assertEqual(unset_repo.workflow_label, "source/repo#11")
        self.assertFalse(unset_repo.read_eligible)
        for operation in (
            changed_cwd,
            sudo_changed_cwd,
            sudo_login,
            nested_changed_cwd,
        ):
            self.assertEqual(operation.kind, "write")
            self.assertIn("dynamic", operation.workflow_key)
        self.assertEqual(reset_by_sudo.kind, "read")
        self.assertIn("dynamic", reset_by_sudo.workflow_key)
        self.assertFalse(reset_by_sudo.read_eligible)
        self.assertEqual(preserved_by_sudo.workflow_label, "owner/repo#11")
        self.assertTrue(preserved_by_sudo.read_eligible)

    def test_cd_segments_update_the_repository_scope(self):
        def repo_for(cwd):
            return {
                "/source": "source/repo",
                "/other": "other/repo",
                "/source/sub": "sub/repo",
            }.get(cwd, "unknown-repo")

        with mock.patch.object(ledger, "_repo_from_cwd", side_effect=repo_for):
            re_anchored = ledger.classify_gh_operations(
                "cd /other && gh pr comment 11 --body done", "/source"
            )[0]
            relative = ledger.classify_gh_operations(
                "cd sub; gh pr comment 11 --body done", "/source"
            )[0]
            failed_guard = ledger.classify_gh_operations(
                "cd /other || gh pr comment 11 --body done", "/source"
            )[0]
            piped = ledger.classify_gh_operations(
                "cd /other | gh pr comment 11 --body done", "/source"
            )[0]
            dynamic_target = ledger.classify_gh_operations(
                'cd "$DIR" && gh pr comment 11 --body done', "/source"
            )[0]
            explicit_repo_wins = ledger.classify_gh_operations(
                "cd /other && gh pr comment 11 --repo named/repo --body done",
                "/source",
            )[0]

        self.assertEqual(re_anchored.workflow_label, "other/repo#11")
        self.assertEqual(relative.workflow_label, "sub/repo#11")
        self.assertEqual(failed_guard.workflow_label, "source/repo#11")
        self.assertEqual(piped.workflow_label, "source/repo#11")
        self.assertIn("dynamic", dynamic_target.workflow_key)
        self.assertEqual(explicit_repo_wins.workflow_label, "named/repo#11")

        unset_host = ledger.classify_gh_operations(
            "GH_HOST=git.example env --unset=GH_HOST "
            "gh pr view 11 --repo owner/repo --json state",
            "/tmp",
        )[0]
        cleared_host = ledger.classify_gh_operations(
            "GH_HOST=git.example env -i GH_REPO=owner/repo gh pr view 11 --json state",
            "/tmp",
        )[0]
        nested_repo = ledger.classify_gh_operations(
            "env GH_REPO=owner/repo bash -c 'gh pr comment 11 --body done'", "/tmp"
        )[0]
        self.assertEqual(unset_host.repo_key, "github:github.com:owner/repo")
        self.assertEqual(cleared_host.repo_key, "github:github.com:owner/repo")
        self.assertEqual(nested_repo.workflow_label, "owner/repo#11")

    def test_wrapper_sentinels_stay_dynamic_and_key_consistently(self):
        self.assertTrue(
            ledger._dynamic_shell_value(ledger.WRAPPER_UNKNOWN_HOST_SENTINEL)
        )
        self.assertTrue(ledger._dynamic_shell_value(ledger.WRAPPER_CWD_SENTINEL))

        write = ledger.classify_gh_operations(
            "GH_HOST=ghe.example.com sudo "
            "gh pr comment 11 --repo owner/repo --body done",
            "/tmp",
        )[0]
        readback = ledger.classify_gh_operations(
            "GH_HOST=ghe.example.com sudo gh pr view 11 --repo owner/repo --json state",
            "/tmp",
        )[0]
        sentinel = ledger.WRAPPER_UNKNOWN_HOST_SENTINEL.lower()
        self.assertIn(sentinel, write.workflow_key)
        self.assertNotIn("ghe.example.com", write.workflow_key)
        # Identically wrapped retries dedupe onto one key, but no read carrying
        # a sentinel is ever eligible: a host-scrubbed write stays unverifiable
        # by design and escapes at the turn boundary.
        self.assertEqual(write.workflow_key, readback.workflow_key)
        self.assertEqual(readback.kind, "read")
        self.assertFalse(readback.read_eligible)

    def test_unrecognized_launchers_stay_out_of_scope(self):
        write = "gh pr comment 11 --repo owner/repo --body done"
        for launcher in (
            f"find . -name x -exec bash -c '{write}' \\;",
            f"parallel bash -c '{write}'",
            f"script -qec 'bash -c \"{write}\"' /dev/null",
            f"su -c '{write}' deploy",
        ):
            with self.subTest(launcher=launcher):
                self.assertEqual(ledger.classify_gh_operations(launcher, "/tmp"), [])

    def test_exec_wrapper_changed_cwd_resolves_relative_graphql_files(self):
        source = Path(self.temporary.name) / "source"
        target = Path(self.temporary.name) / "target"
        source.mkdir()
        target.mkdir()
        (source / "request.graphql").write_text(
            "query Current { viewer { login } }", encoding="utf-8"
        )
        (target / "request.graphql").write_text(
            "mutation Change { addComment(input:{}) { clientMutationId } }",
            encoding="utf-8",
        )
        (source / "request.json").write_text(
            json.dumps({"query": "query Current { viewer { login } }"}),
            encoding="utf-8",
        )

        operation = ledger.classify_gh_operations(
            f"env -C {shlex.quote(str(target))} gh api graphql "
            "-f query=@request.graphql --repo owner/repo",
            str(source),
        )[0]
        with (
            mock.patch.object(
                ledger.Path,
                "stat",
                side_effect=AssertionError("unknown cwd must not stat relative files"),
            ),
            mock.patch.object(
                ledger.Path,
                "read_text",
                side_effect=AssertionError("unknown cwd must not read relative files"),
            ),
        ):
            unknown_cwd = ledger.classify_gh_operations(
                "sudo --login gh api graphql "
                "-f query=@request.graphql --repo owner/repo",
                str(source),
            )[0]
            unknown_input = ledger.classify_gh_operations(
                "sudo --login gh api graphql --input request.json --repo owner/repo",
                str(source),
            )[0]
        absolute_query = ledger.classify_gh_operations(
            "sudo --login gh api graphql "
            f"-f query=@{shlex.quote(str(source / 'request.graphql'))} "
            "--repo owner/repo",
            str(source),
        )[0]
        absolute_input = ledger.classify_gh_operations(
            "sudo --login gh api graphql "
            f"--input {shlex.quote(str(source / 'request.json'))} "
            "--repo owner/repo",
            str(source),
        )[0]
        stdin_query = ledger.classify_gh_operations(
            "sudo --login gh api graphql -f query=@- --repo owner/repo",
            str(source),
        )[0]
        with mock.patch.object(ledger.subprocess, "run") as git:
            self.assertEqual(ledger._repo_from_cwd(None), "unknown-repo")
            git.assert_not_called()

        self.assertEqual(operation.kind, "write")
        self.assertEqual(operation.repo_key, "github:github.com:owner/repo")
        self.assertEqual(unknown_cwd.kind, "unknown")
        self.assertFalse(unknown_cwd.read_eligible)
        self.assertEqual(unknown_input.kind, "unknown")
        self.assertFalse(unknown_input.read_eligible)
        self.assertEqual(absolute_query.kind, "read")
        self.assertEqual(absolute_input.kind, "read")
        self.assertEqual(stdin_query.kind, "unknown")

    def test_exec_wrapper_grammar_rejects_nonexecuting_prefixes(self):
        write = "gh pr comment 11 --repo owner/repo --body done"
        for command in (
            "sudo -u gh pr comment 11 --repo owner/repo --body done",
            f"xargs -I bash -c '{write}'",
            f"nice -n bash -c '{write}'",
            f"stdbuf -o bash -c '{write}'",
            "timeout 5 NOTE=x gh pr comment 11 --repo owner/repo --body done",
            f"timeout 5 NOTE=x bash -c '{write}'",
            f"timeout 5 command bash -c '{write}'",
            "ionice -p gh pr comment 11 --repo owner/repo --body done",
            f"nice --help bash -c '{write}'",
            "env -0 gh pr comment 11 --repo owner/repo --body done",
            "stdbuf gh pr comment 11 --repo owner/repo --body done",
            "nice -n nope gh pr comment 11 --repo owner/repo --body done",
            "timeout nope gh pr comment 11 --repo owner/repo --body done",
            "stdbuf -o1kb gh pr comment 11 --repo owner/repo --body done",
            f"xargs --max-lines=bad bash -c '{write}'",
            f"xargs -n0 bash -c '{write}'",
            f"xargs -L0 bash -c '{write}'",
            f"xargs -s0 bash -c '{write}'",
            f"xargs -0l0 bash -c '{write}'",
            f"xargs -0lbad bash -c '{write}'",
        ):
            with self.subTest(command=command):
                self.assertEqual(ledger.classify_gh_operations(command, "/tmp"), [])

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

    def test_pr_and_issue_create_rekey_to_the_returned_exact_target(self):
        cases = (
            ("pr", "pull", 19, "output"),
            ("issue", "issues", 27, "nested"),
        )
        for group, resource, number, response_shape in cases:
            with self.subTest(group=group):
                state_dir = str(Path(self.state_dir) / f"create-{group}")
                listing = f"gh {group} list --repo owner/repo --limit 20"
                create = f"gh {group} create --repo owner/repo --title created"
                readback = f"gh {group} view {number} --repo owner/repo --json state"
                url = f"https://github.com/owner/repo/{resource}/{number}"
                response = (
                    {"exit_code": 0, "output": url}
                    if response_shape == "output"
                    else {"exit_code": 0, "result": {"stdout": url}}
                )

                ledger.run_hook(
                    hook_payload("PostToolUse", listing, {"exit_code": 0}),
                    agent="codex",
                    mode="enforce",
                    explicit_state_dir=state_dir,
                )
                self.assertIsNone(
                    ledger.run_hook(
                        hook_payload(
                            "PreToolUse", create, tool_use_id=f"create-{group}"
                        ),
                        agent="codex",
                        mode="enforce",
                        explicit_state_dir=state_dir,
                    )
                )
                ledger.run_hook(
                    hook_payload(
                        "PostToolUse",
                        create,
                        response,
                        tool_use_id=f"create-{group}",
                    ),
                    agent="codex",
                    mode="enforce",
                    explicit_state_dir=state_dir,
                )

                connection = ledger.connect_database(state_dir)
                try:
                    pending = connection.execute(
                        """
                        SELECT workflow_label, workflow_key FROM hook_activity
                        WHERE pending_write = 1
                        """
                    ).fetchall()
                finally:
                    connection.close()
                self.assertEqual(
                    [(row["workflow_label"], row["workflow_key"]) for row in pending],
                    [
                        (
                            f"owner/repo#{number}",
                            "github:github.com:owner/repo:"
                            f"{'pull' if group == 'pr' else 'issue'}:number:{number}",
                        )
                    ],
                )

                ledger.run_hook(
                    hook_payload("PostToolUse", readback, {"exit_code": 0}),
                    agent="codex",
                    mode="enforce",
                    explicit_state_dir=state_dir,
                )
                self.assertEqual(
                    ledger.run_hook(
                        hook_payload("Stop"),
                        agent="codex",
                        mode="enforce",
                        explicit_state_dir=state_dir,
                    ),
                    {},
                )

                connection = ledger.connect_database(state_dir)
                try:
                    outcomes = {
                        (row["rule_id"], row["workflow_label"]): row["outcome"]
                        for row in connection.execute("SELECT * FROM encounters")
                    }
                    persisted = "\n".join(
                        str(value)
                        for table in (
                            "encounters",
                            "hook_activity",
                            "hook_sessions",
                            "hook_tools",
                            "hook_completed_tools",
                        )
                        for row in connection.execute(f"SELECT * FROM {table}")
                        for value in row
                    )
                finally:
                    connection.close()
                self.assertEqual(
                    outcomes[("GH-LIVE-STATE-001", f"owner/repo:{group}:create")],
                    "passed",
                )
                self.assertEqual(
                    outcomes[("GH-WRITE-READBACK-001", f"owner/repo#{number}")],
                    "passed",
                )
                self.assertNotIn(url, persisted)
                self.assertNotIn(f"create-{group}", persisted)

    def test_create_output_must_identify_one_matching_target(self):
        listing = "gh pr list --repo owner/repo --limit 20"
        create = "gh pr create --repo owner/repo --title created"
        readback = "gh pr view 19 --repo owner/repo --json state"
        cases = (
            "created without a URL",
            "https://github.com/other/repo/pull/19",
            (
                "https://github.com/owner/repo/pull/19\n"
                "https://github.com/owner/repo/pull/20"
            ),
        )
        for index, output in enumerate(cases):
            with self.subTest(output=output):
                state_dir = str(Path(self.state_dir) / f"create-ambiguous-{index}")
                ledger.run_hook(
                    hook_payload("PostToolUse", listing, {"exit_code": 0}),
                    agent="codex",
                    mode="enforce",
                    explicit_state_dir=state_dir,
                )
                self.assertIsNone(
                    ledger.run_hook(
                        hook_payload(
                            "PreToolUse", create, tool_use_id=f"create-{index}"
                        ),
                        agent="codex",
                        mode="enforce",
                        explicit_state_dir=state_dir,
                    )
                )
                ledger.run_hook(
                    hook_payload(
                        "PostToolUse",
                        create,
                        {"exit_code": 0, "output": output},
                        tool_use_id=f"create-{index}",
                    ),
                    agent="codex",
                    mode="enforce",
                    explicit_state_dir=state_dir,
                )
                ledger.run_hook(
                    hook_payload("PostToolUse", listing, {"exit_code": 0}),
                    agent="codex",
                    mode="enforce",
                    explicit_state_dir=state_dir,
                )
                ledger.run_hook(
                    hook_payload("PostToolUse", readback, {"exit_code": 0}),
                    agent="codex",
                    mode="enforce",
                    explicit_state_dir=state_dir,
                )
                denied = ledger.run_hook(
                    hook_payload("PreToolUse", create),
                    agent="codex",
                    mode="enforce",
                    explicit_state_dir=state_dir,
                )
                self.assertEqual(
                    denied["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                stop = ledger.run_hook(
                    hook_payload("Stop"),
                    agent="codex",
                    mode="audit",
                    explicit_state_dir=state_dir,
                )
                self.assertIn("systemMessage", stop)

                connection = ledger.connect_database(state_dir)
                try:
                    escaped = connection.execute(
                        """
                        SELECT outcome FROM encounters
                        WHERE rule_id = 'GH-WRITE-READBACK-001'
                          AND workflow_label = 'owner/repo:pr:create'
                        """
                    ).fetchone()
                    persisted = "\n".join(
                        str(value)
                        for row in connection.execute("SELECT * FROM encounters")
                        for value in row
                    )
                finally:
                    connection.close()
                self.assertIsNotNone(escaped)
                self.assertEqual(escaped["outcome"], "escaped")
                self.assertNotIn(output, persisted)

    def test_create_result_without_its_pre_mapping_cannot_consume_an_attempt(self):
        listing = "gh pr list --repo owner/repo --limit 20"
        create = "gh pr create --repo owner/repo --title created"
        ledger.run_hook(
            hook_payload("PostToolUse", listing, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload("PreToolUse", create, tool_use_id="mapped-create"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload(
                "PostToolUse",
                create,
                {
                    "exit_code": 0,
                    "output": "https://github.com/owner/repo/pull/20",
                },
                tool_use_id="unmapped-create",
            ),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        ledger.run_hook(
            hook_payload(
                "PostToolUse",
                create,
                {
                    "exit_code": 0,
                    "output": "https://github.com/owner/repo/pull/19",
                },
                tool_use_id="mapped-create",
            ),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload(
                "PostToolUse",
                create,
                {
                    "exit_code": 0,
                    "output": "https://github.com/owner/repo/pull/19",
                },
                tool_use_id="mapped-create",
            ),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        connection = self.connection()
        try:
            pending = {
                row["workflow_label"]: row["pending_count"]
                for row in connection.execute(
                    "SELECT * FROM hook_activity WHERE pending_write = 1"
                )
            }
        finally:
            connection.close()
        self.assertEqual(
            pending,
            {
                "owner/repo:pr:create": 1,
                "owner/repo#19": 0,
            },
        )

    def test_unmapped_failed_create_cannot_be_consumed_by_another_attempt(self):
        listing = "gh issue list --repo owner/repo --limit 20"
        create = "gh issue create --repo owner/repo --title created"
        ledger.run_hook(
            hook_payload("PostToolUse", listing, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload("PreToolUse", create, tool_use_id="mapped-issue-create"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload(
                "PostToolUseFailure", create, tool_use_id="unmapped-issue-create"
            ),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload(
                "PostToolUse",
                create,
                {
                    "exit_code": 0,
                    "output": "https://github.com/owner/repo/issues/31",
                },
                tool_use_id="mapped-issue-create",
            ),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        connection = self.connection()
        try:
            pending = {
                row["workflow_label"]: row["pending_count"]
                for row in connection.execute(
                    "SELECT * FROM hook_activity WHERE pending_write = 1"
                )
            }
        finally:
            connection.close()
        self.assertEqual(
            pending,
            {
                "owner/repo:issue:create": 1,
                "owner/repo#31": 0,
            },
        )

    def test_multiple_creates_in_one_tool_result_stay_generic(self):
        listing = "gh pr list --repo owner/repo --limit 20"
        create = "gh pr create --repo owner/repo --title one"
        compound = f"{create}; gh pr create --repo owner/repo --title two"
        ledger.run_hook(
            hook_payload("PostToolUse", listing, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload("PreToolUse", compound, tool_use_id="compound-create"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload(
                "PostToolUse",
                compound,
                {
                    "exit_code": 0,
                    "output": "https://github.com/owner/repo/pull/19",
                },
                tool_use_id="compound-create",
            ),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        connection = self.connection()
        try:
            pending = connection.execute(
                """
                SELECT workflow_label, pending_count FROM hook_activity
                WHERE pending_write = 1
                """
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(
            [(row["workflow_label"], row["pending_count"]) for row in pending],
            [("owner/repo:pr:create", 2)],
        )

    def test_overlapping_creates_keep_each_unresolved_obligation(self):
        listing = "gh pr list --repo owner/repo --limit 20"
        create = "gh pr create --repo owner/repo --title created"
        readback = "gh pr view 19 --repo owner/repo --json state"
        ledger.run_hook(
            hook_payload("PostToolUse", listing, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        first_pre = ledger.run_hook(
            hook_payload("PreToolUse", create, tool_use_id="create-a"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        second_pre = ledger.run_hook(
            hook_payload("PreToolUse", create, tool_use_id="create-b"),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        self.assertIsNone(first_pre)
        self.assertIn("systemMessage", second_pre)

        ledger.run_hook(
            hook_payload(
                "PostToolUse",
                create,
                {"exit_code": 0, "output": "created without a URL"},
                tool_use_id="create-b",
            ),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload(
                "PostToolUse",
                create,
                {
                    "exit_code": 0,
                    "output": "https://github.com/owner/repo/pull/19",
                },
                tool_use_id="create-a",
            ),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        connection = self.connection()
        try:
            pending = {
                row["workflow_label"]: (row["pending_write"], row["pending_count"])
                for row in connection.execute(
                    "SELECT * FROM hook_activity WHERE pending_write = 1"
                )
            }
        finally:
            connection.close()
        self.assertEqual(
            pending,
            {
                "owner/repo:pr:create": (1, 1),
                "owner/repo#19": (1, 0),
            },
        )

        ledger.run_hook(
            hook_payload("PostToolUse", readback, {"exit_code": 0}),
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
        self.assertIn("owner/repo:pr:create", stop["systemMessage"])

    def test_existing_ledger_adds_create_attempt_count_column(self):
        state_dir = Path(self.state_dir) / "old-schema"
        state_dir.mkdir()
        connection = sqlite3.connect(state_dir / "encounters.sqlite3")
        try:
            connection.execute(
                """
                CREATE TABLE hook_activity (
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    workflow_key TEXT NOT NULL,
                    workflow_label TEXT NOT NULL,
                    repo_key TEXT NOT NULL,
                    preflight_seen INTEGER NOT NULL DEFAULT 0,
                    pending_write INTEGER NOT NULL DEFAULT 0,
                    pending_summary TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, turn_id, workflow_key)
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

        upgraded = ledger.connect_database(str(state_dir))
        try:
            columns = {
                row["name"]
                for row in upgraded.execute("PRAGMA table_info(hook_activity)")
            }
        finally:
            upgraded.close()
        self.assertIn("pending_count", columns)

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

    def test_legacy_claude_fallback_turn_uses_the_existing_session_epoch(self):
        legacy_session_id = "legacy-session-with-current-epoch"
        hashed_session_id = ledger._runtime_id("session", legacy_session_id)
        stale = ledger.isoformat(ledger.utc_now() - timedelta(days=31))
        fresh = ledger.isoformat(ledger.utc_now())
        write = "gh pr comment 62 --repo owner/repo --body done"
        operation = ledger.classify_gh_operations(write, "/tmp")[0]
        connection = self.connection()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO hook_sessions (session_id, epoch, updated_at)
                    VALUES (?, 5, ?)
                    """,
                    (hashed_session_id, stale),
                )
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
                        legacy_session_id,
                        operation.workflow_key,
                        operation.workflow_label,
                        operation.repo_key,
                        operation.summary,
                        fresh,
                    ),
                )
        finally:
            connection.close()

        stop = ledger.run_hook(
            {
                "session_id": legacy_session_id,
                "cwd": "/tmp",
                "hook_event_name": "Stop",
                "stop_hook_active": False,
            },
            agent="claude",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )

        self.assertIn("systemMessage", stop)
        connection = self.connection()
        try:
            activity_count = connection.execute(
                "SELECT COUNT(*) FROM hook_activity"
            ).fetchone()[0]
            session = connection.execute(
                "SELECT epoch, updated_at FROM hook_sessions WHERE session_id = ?",
                (hashed_session_id,),
            ).fetchone()
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
        self.assertEqual(activity_count, 0)
        self.assertIsNotNone(session)
        self.assertEqual(session["epoch"], 5)
        self.assertEqual(session["updated_at"], fresh)
        self.assertEqual(escaped, 1)

    def test_event_transaction_absorbs_a_legacy_write_after_connect(self):
        legacy_session_id = "legacy-session-racing-stop"
        hashed_session_id = ledger._runtime_id("session", legacy_session_id)
        now = ledger.isoformat(ledger.utc_now())
        write = "gh pr comment 63 --repo owner/repo --body done"
        operation = ledger.classify_gh_operations(write, "/tmp")[0]
        connection = self.connection()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO hook_sessions (session_id, epoch, updated_at)
                    VALUES (?, 4, ?)
                    """,
                    (hashed_session_id, now),
                )
        finally:
            connection.close()

        original_connect = ledger.connect_database
        injected = False

        def connect_then_inject(state_dir):
            nonlocal injected
            current = original_connect(state_dir)
            if injected:
                return current
            legacy = sqlite3.connect(Path(state_dir) / "encounters.sqlite3", timeout=2)
            try:
                legacy.execute(
                    """
                    INSERT INTO hook_activity (
                        session_id, turn_id, workflow_key, workflow_label,
                        repo_key, preflight_seen, pending_write,
                        pending_summary, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?)
                    """,
                    (
                        legacy_session_id,
                        legacy_session_id,
                        operation.workflow_key,
                        operation.workflow_label,
                        operation.repo_key,
                        operation.summary,
                        now,
                    ),
                )
                legacy.commit()
            finally:
                legacy.close()
            injected = True
            return current

        payload = {
            "session_id": legacy_session_id,
            "cwd": "/tmp",
            "hook_event_name": "Stop",
            "stop_hook_active": False,
        }
        with mock.patch.object(
            ledger, "connect_database", side_effect=connect_then_inject
        ):
            stop = ledger.run_hook(
                payload,
                agent="claude",
                mode="enforce",
                explicit_state_dir=self.state_dir,
            )

        self.assertEqual(stop["decision"], "block")
        connection = self.connection()
        try:
            raw_rows = connection.execute(
                """
                SELECT COUNT(*) FROM hook_activity
                WHERE session_id = ? OR turn_id = ?
                """,
                (legacy_session_id, legacy_session_id),
            ).fetchone()[0]
            migrated = connection.execute(
                """
                SELECT COUNT(*) FROM hook_activity
                WHERE session_id = ? AND turn_id = 'root:epoch:4'
                  AND pending_write = 1
                """,
                (hashed_session_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(raw_rows, 0)
        self.assertEqual(migrated, 1)

        escaped = ledger.run_hook(
            payload | {"stop_hook_active": True},
            agent="claude",
            mode="enforce",
            explicit_state_dir=self.state_dir,
        )
        self.assertNotIn("decision", escaped)
        self.assertIn("systemMessage", escaped)
        connection = self.connection()
        try:
            activity_count = connection.execute(
                "SELECT COUNT(*) FROM hook_activity"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(activity_count, 0)

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

    def test_enforcement_denial_has_no_post_and_stop_blocks_once(self):
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
        self.assertNotIn("decision", final_stop)
        self.assertIn("systemMessage", final_stop)
        cleared = ledger.run_hook(
            hook_payload("Stop"),
            agent="codex",
            mode="enforce",
            explicit_state_dir=self.state_dir,
        )
        self.assertEqual(cleared, {})

    def test_flags_before_the_target_key_the_same_exact_object(self):
        read = "gh pr view --repo owner/repo 11 --json state"
        write = "gh pr comment --repo owner/repo 11 --body done"
        canonical = "gh pr view 11 --repo owner/repo --json state"
        read_operation = ledger.classify_gh_operations(read, "/tmp")[0]
        write_operation = ledger.classify_gh_operations(write, "/tmp")[0]
        canonical_operation = ledger.classify_gh_operations(canonical, "/tmp")[0]
        self.assertEqual(read_operation.workflow_key, canonical_operation.workflow_key)
        self.assertEqual(write_operation.workflow_key, canonical_operation.workflow_key)
        self.assertEqual(write_operation.workflow_label, "owner/repo#11")
        self.assertTrue(read_operation.read_eligible)

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
            hook_payload("PostToolUse", write, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=self.state_dir,
        )
        ledger.run_hook(
            hook_payload("PostToolUse", read, {"exit_code": 0}),
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

    def test_boolean_short_flags_before_the_number_keep_the_target(self):
        cases = (
            ("gh pr merge -s 11 --repo owner/repo", "owner/repo#11"),
            ("gh pr merge -m 11 --repo owner/repo", "owner/repo#11"),
            ("gh pr review -a 11 --repo owner/repo", "owner/repo#11"),
            ("gh pr checkout -f 11 --repo owner/repo", "owner/repo#11"),
            ("gh issue edit -m 12 99 --repo owner/repo", "owner/repo#99"),
            ("gh issue edit 99 -m 12 --repo owner/repo", "owner/repo#99"),
            ("gh pr edit -m 12 99 --repo owner/repo", "owner/repo#99"),
            ("gh pr edit 99 -m 12 --repo owner/repo", "owner/repo#99"),
            ("gh pr view --json state 11 --repo owner/repo", "owner/repo#11"),
        )
        for command, label in cases:
            with self.subTest(command=command):
                operation = ledger.classify_gh_operations(command, "/tmp")[0]
                self.assertEqual(operation.workflow_label, label)

        no_target = ledger.classify_gh_operations(
            "gh pr checks -i 5 --repo owner/repo", "/tmp"
        )[0]
        explicit_target = ledger.classify_gh_operations(
            "gh pr checks -i 5 11 --repo owner/repo", "/tmp"
        )[0]
        self.assertNotEqual(no_target.workflow_label, "owner/repo#5")
        self.assertEqual(explicit_target.workflow_label, "owner/repo#11")

    def test_action_specific_flag_arity_preserves_exact_authorization(self):
        wrong_read = "gh issue view 12 --repo owner/repo --json state"
        right_read = "gh issue view 99 --repo owner/repo --json state"
        issue_write = "gh issue edit -m 12 99 --repo owner/repo --title fixed"
        pr_read = "gh pr view 11 --repo owner/repo --json state"
        pr_review = "gh pr review -a 11 --repo owner/repo"
        pr_checkout = "gh pr checkout -f 11 --repo owner/repo"

        wrong_state = str(Path(self.state_dir) / "wrong-milestone-target")
        ledger.run_hook(
            hook_payload("PostToolUse", wrong_read, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=wrong_state,
        )
        denied = ledger.run_hook(
            hook_payload("PreToolUse", issue_write),
            agent="codex",
            mode="audit",
            explicit_state_dir=wrong_state,
        )
        self.assertIn("systemMessage", denied)

        right_state = str(Path(self.state_dir) / "right-milestone-target")
        ledger.run_hook(
            hook_payload("PostToolUse", right_read, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=right_state,
        )
        self.assertIsNone(
            ledger.run_hook(
                hook_payload("PreToolUse", issue_write),
                agent="codex",
                mode="audit",
                explicit_state_dir=right_state,
            )
        )

        state_dir = str(Path(self.state_dir) / "pr-review-approve")
        ledger.run_hook(
            hook_payload("PostToolUse", pr_read, {"exit_code": 0}),
            agent="codex",
            mode="audit",
            explicit_state_dir=state_dir,
        )
        self.assertIsNone(
            ledger.run_hook(
                hook_payload("PreToolUse", pr_review),
                agent="codex",
                mode="audit",
                explicit_state_dir=state_dir,
            )
        )
        self.assertEqual(
            ledger.classify_gh_operations(pr_checkout, "/tmp")[0].workflow_key,
            ledger.classify_gh_operations(pr_read, "/tmp")[0].workflow_key,
        )

    def test_inline_variable_mutations_are_tracked_as_writes(self):
        command = (
            "gh api graphql -f query='mutation($input:CloseIssueInput!) "
            "{ closeIssue(input:$input) { clientMutationId } }'"
        )
        operation = ledger.classify_gh_operations(command, "/tmp")[0]
        self.assertEqual(operation.kind, "write")
        self.assertFalse(operation.read_eligible)

        opaque = "gh api graphql -f 'query=$GENERATED_QUERY'"
        self.assertEqual(
            ledger.classify_gh_operations(opaque, "/tmp")[0].kind, "unknown"
        )

    def test_inline_graphql_selection_ignores_non_operation_mutation_tokens(self):
        mixed = (
            "query Q($mutation:String){viewer{login}} "
            "mutation M($input:CloseIssueInput!){"
            "closeIssue(input:$input){clientMutationId}}"
        )
        selected_query = ledger.classify_gh_operations(
            f"gh api graphql -f operationName=Q -f 'query={mixed}'", "/tmp"
        )[0]
        selected_mutation = ledger.classify_gh_operations(
            f"gh api graphql -f operationName=M -f 'query={mixed}'", "/tmp"
        )[0]
        unselected = ledger.classify_gh_operations(
            f"gh api graphql -f 'query={mixed}'", "/tmp"
        )[0]
        named_mutation = ledger.classify_gh_operations(
            "gh api graphql -f 'query=query mutation { viewer { login } }'",
            "/tmp",
        )[0]
        fragment_named_mutation = ledger.classify_gh_operations(
            "gh api graphql -f 'query=fragment mutation on User { login } "
            "query Q { viewer { ...mutation } }'",
            "/tmp",
        )[0]
        anonymous_directive = ledger.classify_gh_operations(
            "gh api graphql -f 'query=query @trace { viewer { login } }'",
            "/tmp",
        )[0]

        self.assertEqual(selected_query.kind, "unknown")
        self.assertFalse(selected_query.read_eligible)
        self.assertEqual(selected_mutation.kind, "write")
        self.assertFalse(selected_mutation.read_eligible)
        self.assertEqual(unselected.kind, "write")
        self.assertEqual(named_mutation.kind, "read")
        self.assertEqual(fragment_named_mutation.kind, "read")
        self.assertEqual(anonymous_directive.kind, "read")

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

    def test_claude_issue_create_rekeys_from_stdout(self):
        session_id = "claude-create-issue"
        listing = "gh issue list --repo owner/repo --limit 20"
        create = "gh issue create --repo owner/repo --title created"
        readback = "gh issue view 31 --repo owner/repo --json state"
        self.run_successful_command(
            listing,
            session_id=session_id,
            tool_use_id="toolu_create_issue_list",
        )
        self.assertIsNone(
            self.run_hook(
                claude_payload(
                    "PreToolUse",
                    create,
                    session_id=session_id,
                    tool_use_id="toolu_create_issue",
                ),
                mode="enforce",
            )
        )
        self.run_hook(
            claude_payload(
                "PostToolUse",
                create,
                dict(
                    CLAUDE_BASH_OK,
                    stdout="https://github.com/owner/repo/issues/31\n",
                ),
                session_id=session_id,
                tool_use_id="toolu_create_issue",
            ),
            mode="enforce",
        )
        self.run_successful_command(
            readback,
            session_id=session_id,
            tool_use_id="toolu_create_issue_readback",
        )
        self.assertEqual(
            self.run_hook(
                claude_payload("Stop", session_id=session_id), mode="enforce"
            ),
            {},
        )

        connection = ledger.connect_database(self.state_dir)
        try:
            outcomes = {
                (row["rule_id"], row["workflow_label"]): row["outcome"]
                for row in connection.execute("SELECT * FROM encounters")
            }
        finally:
            connection.close()
        self.assertEqual(
            outcomes[("GH-LIVE-STATE-001", "owner/repo:issue:create")],
            "passed",
        )
        self.assertEqual(
            outcomes[("GH-WRITE-READBACK-001", "owner/repo#31")],
            "passed",
        )

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

    def test_claude_enforcement_denial_has_no_post_and_stop_blocks_once(self):
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
        self.assertNotIn("decision", reentry)
        self.assertIn("systemMessage", reentry)
        self.assert_readback_escaped("owner/repo#12")
        cleared = self.run_hook(
            claude_payload("Stop", session_id=session_id, stop_hook_active=False),
            mode="enforce",
        )
        self.assertEqual(cleared, {})

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
