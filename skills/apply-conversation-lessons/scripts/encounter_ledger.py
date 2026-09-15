#!/usr/bin/env python3
"""Shared encounter ledger and lifecycle-hook adapter for SECQUOIA skills.

Encounter history stores rule identifiers, workflow labels, agent names, outcomes,
and skill revisions. Transient hook state uses hashed lifecycle identifiers. The
runner never reads or persists prompts or transcripts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


INSTALLATION_ID = "secquoia-encounter-ledger"
DEFAULT_DEDUPE_HOURS = 24
DEFAULT_REPORT_DAYS = 30
DEFAULT_MIN_ENCOUNTERS = 3
HOOK_STATE_RETENTION_DAYS = 30
MAX_NESTED_SHELL_DEPTH = 32
MAX_TOOL_RESPONSE_SCAN_CHARS = 32_000
OUTCOME_RANK = {"passed": 0, "prevented": 1, "escaped": 2}

RULES = {
    "GH-LIVE-STATE-001": {
        "skill": "gh-workflow-conventions",
        "severity": "medium",
        "description": "A GitHub write needs a separate successful live-state read first.",
    },
    "GH-WRITE-READBACK-001": {
        "skill": "gh-workflow-conventions",
        "severity": "medium",
        "description": "A successful GitHub write needs a separate readback before stopping.",
    },
}

READ_ACTIONS = {
    "pr": {"checks", "checkout", "diff", "list", "status", "view"},
    "issue": {"list", "status", "view"},
    "repo": {"clone", "list", "view"},
    "run": {"download", "list", "view", "watch"},
    "release": {"download", "list", "view"},
    "workflow": {"list", "view"},
    "label": {"list"},
    "secret": {"list"},
    "variable": {"list"},
    "search": {"code", "commits", "issues", "prs", "repos"},
}

WRITE_ACTIONS = {
    "pr": {
        "close",
        "comment",
        "create",
        "edit",
        "lock",
        "merge",
        "ready",
        "reopen",
        "review",
        "unlock",
    },
    "issue": {
        "close",
        "comment",
        "create",
        "delete",
        "develop",
        "edit",
        "lock",
        "pin",
        "reopen",
        "transfer",
        "unlock",
        "unpin",
    },
    "release": {"create", "delete", "delete-asset", "edit", "upload"},
    "repo": {
        "archive",
        "create",
        "delete",
        "deploy-key",
        "edit",
        "fork",
        "rename",
        "set-default",
        "sync",
        "unarchive",
    },
    "workflow": {"disable", "enable", "run"},
    "run": {"cancel", "delete", "rerun"},
    "label": {"clone", "create", "delete", "edit"},
    "secret": {"delete", "set"},
    "variable": {"delete", "set"},
}

TARGETED_ACTIONS = {
    "pr": (READ_ACTIONS["pr"] | WRITE_ACTIONS["pr"]) - {"list", "status", "create"},
    "issue": (READ_ACTIONS["issue"] | WRITE_ACTIONS["issue"])
    - {"list", "status", "create"},
    "release": (READ_ACTIONS["release"] | WRITE_ACTIONS["release"]) - {"list"},
    "run": (READ_ACTIONS["run"] | WRITE_ACTIONS["run"]) - {"list"},
    "workflow": (READ_ACTIONS["workflow"] | WRITE_ACTIONS["workflow"]) - {"list"},
    "repo": (READ_ACTIONS["repo"] | WRITE_ACTIONS["repo"]) - {"list", "create"},
    "label": WRITE_ACTIONS["label"] - {"clone"},
    "secret": WRITE_ACTIONS["secret"],
    "variable": WRITE_ACTIONS["variable"],
}

IGNORED_GROUPS = {
    "--help",
    "--version",
    "alias",
    "auth",
    "completion",
    "config",
    "extension",
    "help",
    "version",
}

FLAGS_WITH_VALUES = {
    "--body",
    "--body-file",
    "--hostname",
    "--field",
    "--input",
    "--jq",
    "--method",
    "--repo",
    "--raw-field",
    "--template",
    "--title",
    "--user",
    "-F",
    "-H",
    "-R",
    "-f",
    "-X",
}

# Common gh flags that consume the next token as their value. Positional
# target extraction must skip these so a flag placed before the target
# ("gh pr comment --repo o/r 11") keys the same object as the flag-after
# form ("gh pr comment 11 --repo o/r").
GH_VALUE_FLAGS = FLAGS_WITH_VALUES | {
    "--add-assignee",
    "--add-label",
    "--add-project",
    "--add-reviewer",
    "--assignee",
    "--attempt",
    "--author",
    "--base",
    "--branch",
    "--category",
    "--color",
    "--discussion-category",
    "--head",
    "--interval",
    "--job",
    "--json",
    "--label",
    "--limit",
    "--milestone",
    "--notes",
    "--notes-file",
    "--output",
    "--pattern",
    "--project",
    "--reason",
    "--ref",
    "--remove-assignee",
    "--remove-label",
    "--remove-project",
    "--remove-reviewer",
    "--reviewer",
    "--search",
    "--state",
    "--subject",
    "--tag",
    "-A",
    "-B",
    "-L",
    "-S",
    "-a",
    "-b",
    "-i",
    "-l",
    "-n",
    "-q",
    "-t",
}

# Short-flag arity is action-specific in gh. For example, -a is a value for
# `pr edit` but boolean --approve for `pr review`; -f is a GraphQL field but
# boolean --force for `pr checkout`; and -m is a milestone value for edit but
# boolean --merge for `pr merge`.
GH_ACTION_BOOLEAN_FLAGS = {
    ("pr", "checkout"): {"-f"},
    ("pr", "merge"): {"-m", "-s"},
    ("pr", "review"): {"-a"},
}
GH_ACTION_VALUE_FLAGS = {
    ("issue", "edit"): {"-m"},
    ("pr", "edit"): {"-m"},
}


@dataclass(frozen=True)
class GhOperation:
    kind: str
    workflow_key: str
    workflow_label: str
    repo_key: str
    summary: str
    read_eligible: bool = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _runtime_id(kind: str, value: Any) -> str:
    encoded = f"{kind}:{value}".encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()[:32]


def _current_runtime_id(value: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{32}", value) is not None


def _current_turn_id(value: str) -> bool:
    return (
        re.fullmatch(r"(?:root|[0-9a-f]{32}):(?:epoch:\d+|[0-9a-f]{32})", value)
        is not None
    )


def _migrate_legacy_hook_state(connection: sqlite3.Connection) -> None:
    """Replace pre-hashing lifecycle identifiers without losing pending state.

    This runs on every connect by design: a mixed-version window (one agent on
    an older script writing raw identifiers into the shared ledger) can add
    legacy rows to an already-migrated database, and the 30-day pruning keeps
    the scanned table small.
    """
    rows = connection.execute("SELECT * FROM hook_activity").fetchall()
    legacy_rows = [
        row
        for row in rows
        if not _current_runtime_id(str(row["session_id"]))
        or not _current_turn_id(str(row["turn_id"]))
    ]
    if not legacy_rows:
        return

    for row in legacy_rows:
        raw_session = str(row["session_id"])
        raw_turn = str(row["turn_id"])
        session_id = (
            raw_session
            if _current_runtime_id(raw_session)
            else _runtime_id("session", raw_session)
        )
        if _current_turn_id(raw_turn):
            turn_id = raw_turn
        elif raw_turn == raw_session:
            session = connection.execute(
                "SELECT epoch FROM hook_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            epoch = int(session["epoch"]) if session else 0
            turn_id = f"root:epoch:{epoch}"
            if session:
                # Pruning runs immediately after migration. Keep a current
                # session row alive when a newer legacy activity row proves
                # that the session is still active.
                connection.execute(
                    """
                    UPDATE hook_sessions
                    SET updated_at = MAX(updated_at, ?)
                    WHERE session_id = ?
                    """,
                    (row["updated_at"], session_id),
                )
        else:
            turn_id = f"root:{_runtime_id('turn', raw_turn)}"
        connection.execute(
            """
            INSERT INTO hook_activity (
                session_id, turn_id, workflow_key, workflow_label, repo_key,
                preflight_seen, pending_write, pending_count, pending_summary,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, turn_id, workflow_key) DO UPDATE SET
                workflow_label = excluded.workflow_label,
                repo_key = excluded.repo_key,
                preflight_seen = MAX(
                    hook_activity.preflight_seen, excluded.preflight_seen
                ),
                pending_write = MAX(
                    hook_activity.pending_write, excluded.pending_write
                ),
                pending_count = MAX(
                    hook_activity.pending_count, excluded.pending_count
                ),
                pending_summary = CASE
                    WHEN excluded.pending_write = 1
                    THEN excluded.pending_summary
                    ELSE hook_activity.pending_summary
                END,
                updated_at = MAX(hook_activity.updated_at, excluded.updated_at)
            """,
            (
                session_id,
                turn_id,
                row["workflow_key"],
                row["workflow_label"],
                row["repo_key"],
                row["preflight_seen"],
                row["pending_write"],
                row["pending_count"],
                row["pending_summary"],
                row["updated_at"],
            ),
        )
        connection.execute(
            """
            DELETE FROM hook_activity
            WHERE session_id = ? AND turn_id = ? AND workflow_key = ?
            """,
            (raw_session, raw_turn, row["workflow_key"]),
        )


def state_directory(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state) / "secquoia-agent-skills"
    return Path.home() / ".local" / "state" / "secquoia-agent-skills"


def connect_database(explicit_state_dir: str | None = None) -> sqlite3.Connection:
    directory = state_directory(explicit_state_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    database = directory / "encounters.sqlite3"
    connection = sqlite3.connect(database, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=2000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS encounters (
            id INTEGER PRIMARY KEY,
            rule_id TEXT NOT NULL,
            workflow_key TEXT NOT NULL,
            workflow_label TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            first_agent TEXT NOT NULL,
            last_agent TEXT NOT NULL,
            agents_json TEXT NOT NULL,
            first_skill_revision TEXT NOT NULL,
            last_skill_revision TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK (outcome IN ('passed', 'prevented', 'escaped')),
            attempts INTEGER NOT NULL DEFAULT 1,
            detail TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS encounters_lookup
            ON encounters(rule_id, workflow_key, last_seen);

        CREATE TABLE IF NOT EXISTS hook_activity (
            session_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            workflow_key TEXT NOT NULL,
            workflow_label TEXT NOT NULL,
            repo_key TEXT NOT NULL,
            preflight_seen INTEGER NOT NULL DEFAULT 0,
            pending_write INTEGER NOT NULL DEFAULT 0,
            pending_count INTEGER NOT NULL DEFAULT 0,
            pending_summary TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (session_id, turn_id, workflow_key)
        );
        CREATE INDEX IF NOT EXISTS hook_activity_turn
            ON hook_activity(session_id, turn_id, pending_write);

        CREATE TABLE IF NOT EXISTS hook_sessions (
            session_id TEXT PRIMARY KEY,
            epoch INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS hook_tools (
            session_id TEXT NOT NULL,
            tool_use_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (session_id, tool_use_id)
        );
        CREATE INDEX IF NOT EXISTS hook_tools_turn
            ON hook_tools(session_id, turn_id);

        CREATE TABLE IF NOT EXISTS hook_completed_tools (
            session_id TEXT NOT NULL,
            tool_use_id TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (session_id, tool_use_id)
        );
        """
    )
    with _write_transaction(connection):
        activity_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(hook_activity)").fetchall()
        }
        if "pending_count" not in activity_columns:
            connection.execute(
                "ALTER TABLE hook_activity "
                "ADD COLUMN pending_count INTEGER NOT NULL DEFAULT 0"
            )
    stale_cutoff = isoformat(utc_now() - timedelta(days=HOOK_STATE_RETENTION_DAYS))
    with _write_transaction(connection):
        _migrate_legacy_hook_state(connection)
        for table in (
            "hook_activity",
            "hook_tools",
            "hook_sessions",
            "hook_completed_tools",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE updated_at < ?", (stale_cutoff,)
            )
    return connection


@contextmanager
def report_database(
    explicit_state_dir: str | None = None,
) -> Iterator[sqlite3.Connection | None]:
    """Open a current ledger view without writing to its state directory."""
    database = state_directory(explicit_state_dir) / "encounters.sqlite3"
    if not database.is_file():
        yield None
        return

    sidecars = tuple(
        database.with_name(f"{database.name}{suffix}") for suffix in ("-wal", "-shm")
    )
    with tempfile.TemporaryDirectory(prefix="secquoia-ledger-report-") as temporary:
        snapshot = Path(temporary) / database.name
        for _ in range(3):
            sidecar_state = tuple(path.exists() for path in sidecars)
            if all(sidecar_state):
                uri = f"{database.resolve().as_uri()}?mode=ro"
                connection = None
                try:
                    connection = sqlite3.connect(uri, uri=True, timeout=2)
                    connection.row_factory = sqlite3.Row
                    connection.execute("PRAGMA query_only=ON")
                    connection.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
                except sqlite3.OperationalError:
                    if connection is not None:
                        connection.close()
                    continue
                try:
                    yield connection
                finally:
                    connection.close()
                return
            if any(sidecar_state):
                continue
            before = database.stat()
            shutil.copyfile(database, snapshot)
            after = database.stat()
            stable = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            if not stable or any(path.exists() for path in sidecars):
                continue

            connection = sqlite3.connect(snapshot, timeout=2)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            try:
                yield connection
            finally:
                connection.close()
            return

    raise sqlite3.OperationalError(
        "encounter ledger changed while opening; rerun the report"
    )


@contextmanager
def _write_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Serialize a logical state transition while allowing nested helpers."""
    outer_transaction = connection.in_transaction
    if not outer_transaction:
        connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        if not outer_transaction:
            connection.rollback()
        raise
    else:
        if not outer_transaction:
            connection.commit()


def skill_revision() -> str:
    override = os.environ.get("SECQUOIA_SKILL_REVISION")
    if override:
        return override
    installed_revision = Path(__file__).with_name(".installed-revision")
    if installed_revision.is_file():
        value = installed_revision.read_text(encoding="utf-8").strip()
        if value:
            return value
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / ".git").exists():
            try:
                result = subprocess.run(
                    ["git", "-C", str(parent), "rev-parse", "HEAD"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                return result.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                break
    return "unknown"


def _workflow_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()[:24]


def record_encounter(
    connection: sqlite3.Connection,
    *,
    rule_id: str,
    workflow_id: str,
    workflow_label: str,
    agent: str,
    outcome: str,
    revision: str,
    detail: str = "",
    now: datetime | None = None,
    dedupe_hours: int = DEFAULT_DEDUPE_HOURS,
) -> int:
    if outcome not in OUTCOME_RANK:
        raise ValueError(f"unknown outcome: {outcome}")
    if rule_id not in RULES:
        raise ValueError(f"unknown rule id: {rule_id}")
    current = now or utc_now()
    current_text = isoformat(current)
    cutoff = isoformat(current - timedelta(hours=dedupe_hours))
    workflow_key = _workflow_hash(workflow_id)
    with _write_transaction(connection):
        row = connection.execute(
            """
            SELECT * FROM encounters
            WHERE rule_id = ? AND workflow_key = ? AND last_seen >= ?
            ORDER BY last_seen DESC LIMIT 1
            """,
            (rule_id, workflow_key, cutoff),
        ).fetchone()
        if row is None:
            cursor = connection.execute(
                """
                INSERT INTO encounters (
                    rule_id, workflow_key, workflow_label, first_seen, last_seen,
                    first_agent, last_agent, agents_json, first_skill_revision,
                    last_skill_revision, outcome, attempts, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    rule_id,
                    workflow_key,
                    workflow_label,
                    current_text,
                    current_text,
                    agent,
                    agent,
                    json.dumps([agent]),
                    revision,
                    revision,
                    outcome,
                    detail,
                ),
            )
            return int(cursor.lastrowid)

        agents = set(json.loads(row["agents_json"]))
        agents.add(agent)
        strongest = max((row["outcome"], outcome), key=OUTCOME_RANK.__getitem__)
        connection.execute(
            """
            UPDATE encounters
            SET last_seen = ?, last_agent = ?, agents_json = ?,
                last_skill_revision = ?, outcome = ?, attempts = attempts + 1,
                detail = CASE WHEN ? = '' THEN detail ELSE ? END
            WHERE id = ?
            """,
            (
                current_text,
                agent,
                json.dumps(sorted(agents)),
                revision,
                strongest,
                detail,
                detail,
                row["id"],
            ),
        )
        return int(row["id"])


def report_encounters(
    connection: sqlite3.Connection,
    *,
    since_days: int = DEFAULT_REPORT_DAYS,
    min_encounters: int = DEFAULT_MIN_ENCOUNTERS,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    cutoff = isoformat((now or utc_now()) - timedelta(days=since_days))
    agents_by_rule: dict[str, set[str]] = {}
    for agent_row in connection.execute(
        "SELECT rule_id, agents_json FROM encounters WHERE last_seen >= ?", (cutoff,)
    ).fetchall():
        try:
            agents = json.loads(agent_row["agents_json"])
        except (TypeError, json.JSONDecodeError):
            agents = []
        if isinstance(agents, list):
            agents_by_rule.setdefault(agent_row["rule_id"], set()).update(
                str(agent) for agent in agents if agent
            )
    rows = connection.execute(
        """
        SELECT
            rule_id,
            COUNT(*) AS opportunities,
            SUM(CASE WHEN outcome != 'passed' THEN 1 ELSE 0 END) AS violations,
            SUM(CASE WHEN outcome = 'prevented' THEN 1 ELSE 0 END) AS prevented,
            SUM(CASE WHEN outcome = 'escaped' THEN 1 ELSE 0 END) AS escaped,
            COUNT(DISTINCT workflow_key) AS distinct_targets,
            GROUP_CONCAT(DISTINCT last_skill_revision) AS revisions,
            MIN(first_seen) AS first_seen,
            MAX(last_seen) AS last_seen
        FROM encounters
        WHERE last_seen >= ?
        GROUP BY rule_id
        HAVING violations >= ?
        ORDER BY violations DESC, rule_id
        """,
        (cutoff, min_encounters),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        rule = RULES[row["rule_id"]]
        result.append(
            {
                "rule_id": row["rule_id"],
                "skill": rule["skill"],
                "severity": rule["severity"],
                "description": rule["description"],
                "opportunities": row["opportunities"],
                "violations": row["violations"],
                "prevented": row["prevented"],
                "escaped": row["escaped"],
                "distinct_targets": row["distinct_targets"],
                "agents": sorted(agents_by_rule.get(row["rule_id"], set())),
                "revisions": sorted(filter(None, (row["revisions"] or "").split(","))),
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
            }
        )
    return result


def _normalize_repo(value: str) -> str:
    value = value.strip().removesuffix(".git")
    if value.startswith("git@github.com:"):
        return value.split(":", 1)[1]
    match = re.search(r"github\.com[/:]([^/]+/[^/]+)$", value)
    if match:
        return match.group(1)
    return value or "unknown-repo"


def _repo_from_cwd(cwd: str | None) -> str:
    if cwd is None:
        return "unknown-repo"
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "config", "--get", "remote.origin.url"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return _normalize_repo(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return "unknown-repo"


_CD_OPTION_TOKENS = frozenset({"-L", "-P", "-e", "-@"})


def _cd_segment_directory(
    segment: list[str], current: str | None
) -> tuple[bool, str | None]:
    """Interpret a shell segment as a ``cd`` builtin invocation.

    Returns ``(is_cd, new_directory)``. ``new_directory`` is ``None`` when the
    destination cannot be resolved statically: a dynamic value, ``cd -``, no
    argument, extra arguments, or a relative path from an unknown directory."""
    if not segment or segment[0] != "cd":
        return False, None
    args = list(segment[1:])
    while args and args[0] in _CD_OPTION_TOKENS:
        args.pop(0)
    if args and args[0] == "--":
        args.pop(0)
    if len(args) != 1:
        return True, None
    target = args[0]
    if target == "-" or _dynamic_shell_value(target):
        return True, None
    if target.startswith("~"):
        target = os.path.expanduser(target)
    if os.path.isabs(target):
        return True, os.path.normpath(target)
    if current is None:
        return True, None
    return True, os.path.normpath(os.path.join(current, target))


def _tokenize_shell(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return shlex.split(command.replace("\n", ";"), posix=False)


def _gh_token(token: str) -> str | None:
    return "gh" if Path(token).name == "gh" else None


def _command_substitutions(command: str) -> Iterable[str]:
    """Yield executable command substitutions, excluding single-quoted text."""
    index = 0
    quote = ""
    while index < len(command):
        char = command[index]
        if char == "\\":
            index += 2
            continue
        if quote == "'":
            if char == "'":
                quote = ""
            index += 1
            continue
        if char == "'" and not quote:
            quote = "'"
            index += 1
            continue
        if char == '"':
            quote = "" if quote == '"' else ('"' if not quote else quote)
            index += 1
            continue
        if char == "`":
            end = index + 1
            while end < len(command):
                if command[end] == "\\":
                    end += 2
                    continue
                if command[end] == "`":
                    yield command[index + 1 : end]
                    index = end + 1
                    break
                end += 1
            else:
                return
            continue
        prefixed_parenthesis = (
            char in "$<>"
            and index + 1 < len(command)
            and command[index + 1] == "("
            and (char == "$" or not quote)
        )
        grouped_parenthesis = (
            char == "("
            and not quote
            and (index == 0 or command[index - 1] not in "$<>")
        )
        if prefixed_parenthesis or grouped_parenthesis:
            start = index + (2 if prefixed_parenthesis else 1)
            end = start
            depth = 1
            inner_quote = ""
            while end < len(command):
                inner = command[end]
                if inner == "\\":
                    end += 2
                    continue
                if inner_quote == "'":
                    if inner == "'":
                        inner_quote = ""
                    end += 1
                    continue
                if inner == "'" and not inner_quote:
                    inner_quote = "'"
                elif inner == '"':
                    inner_quote = (
                        ""
                        if inner_quote == '"'
                        else ('"' if not inner_quote else inner_quote)
                    )
                elif not inner_quote and inner == "(":
                    depth += 1
                elif not inner_quote and inner == ")":
                    depth -= 1
                    if depth == 0:
                        yield command[start:end]
                        index = end + 1
                        break
                end += 1
            else:
                return
            continue
        index += 1


@dataclass(frozen=True)
class _ExecWrapperGrammar:
    value_options: frozenset[str] = frozenset()
    boolean_options: frozenset[str] = frozenset()
    optional_inline_value_options: frozenset[str] = frozenset()
    terminal_options: frozenset[str] = frozenset()
    nonexecuting_options: frozenset[str] = frozenset()
    wait_options: frozenset[str] = frozenset()
    detaching_options: frozenset[str] = frozenset()
    scope_options: frozenset[str] = frozenset()
    cwd_value_options: frozenset[str] = frozenset()
    unknown_cwd_options: frozenset[str] = frozenset()
    required_any_options: frozenset[str] = frozenset()
    preserve_environment_options: frozenset[str] = frozenset()
    positional_operands: int = 0
    numeric_adjustment: bool = False
    short_option_clusters: bool = False
    command_environment: bool = False
    scrubs_environment: bool = False


@dataclass(frozen=True)
class _WrapperConsumption:
    span: int
    read_success_coupled: bool
    repository_scope_changed: bool = False
    working_directory_changed: bool = False
    working_directory: str | None = None
    command_environment: dict[str, str] | None = None
    scrubs_environment: bool = False
    preserve_all_environment: bool = False
    preserved_environment: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _EnvConsumption:
    span: int
    environment: dict[str, str]
    unset_variables: frozenset[str]
    clear_environment: bool
    repository_scope_changed: bool
    working_directory: str | None
    split_command: str | None = None


@dataclass(frozen=True)
class _ExecutionContext:
    environment: dict[str, str]
    read_success_coupled: bool = True
    repository_scope_changed: bool = False
    host_environment_reset: bool = False
    host_environment_uncertain: bool = False
    working_directory: str | None = None


# Token sentinels represent repository scope or hostname that a wrapper makes
# unknowable. Their leading "$" routes them through _dynamic_shell_value, so an
# operation carrying one can never be read-eligible or exact-scope evidence.
# The text is stable on purpose: identically wrapped retries normalize to the
# same workflow key and dedupe into one episode. Verification stays fail-closed —
# no eligible read can ever share a sentinel key, so a host- or scope-scrubbed
# write keeps its readback obligation until the turn escapes; rerun the write
# without the scrubbing wrapper (or with sudo -E) to make it verifiable.
# Unknown working directories remain None instead of becoming a filesystem
# path: relative @file inputs then fail closed without touching the filesystem.
WRAPPER_UNKNOWN_HOST_SENTINEL = "$SECQUOIA_WRAPPER_UNKNOWN_HOST"
WRAPPER_CWD_SENTINEL = "$SECQUOIA_WRAPPER_CWD"

# These wrappers execute a following command, but only when their option grammar
# is known. Unknown options fail closed: guessing whether they consume a value
# can otherwise hide the real command or expose inert argument text as `gh`.
# Launchers outside these tables (for example `find -exec`, `parallel`,
# `script -c`, `ssh`, or `su -c`) are deliberately out of scope: their
# prefixes never parse as executable, so nothing behind them can authorize a
# write, and gh writes behind them stay untracked — the README's "workflow
# guard, not a security sandbox" boundary. Extend a grammar rather than
# loosening the parser when a new wrapper matters.
EXEC_THROUGH_WRAPPERS = {
    "ionice": _ExecWrapperGrammar(
        value_options=frozenset({"-c", "-n", "--class", "--classdata"}),
        boolean_options=frozenset({"-t", "--ignore"}),
        terminal_options=frozenset({"-h", "-V", "--help", "--version"}),
        nonexecuting_options=frozenset({"-p", "-P", "-u", "--pid", "--pgid", "--uid"}),
    ),
    "nice": _ExecWrapperGrammar(
        value_options=frozenset({"-n", "--adjustment"}),
        terminal_options=frozenset({"--help", "--version"}),
        numeric_adjustment=True,
    ),
    "nohup": _ExecWrapperGrammar(terminal_options=frozenset({"--help", "--version"})),
    "setsid": _ExecWrapperGrammar(
        boolean_options=frozenset({"-c", "-f", "-w", "--ctty", "--fork", "--wait"}),
        terminal_options=frozenset({"-h", "-V", "--help", "--version"}),
        wait_options=frozenset({"-w", "--wait"}),
        short_option_clusters=True,
    ),
    "stdbuf": _ExecWrapperGrammar(
        value_options=frozenset({"-e", "-i", "-o", "--error", "--input", "--output"}),
        terminal_options=frozenset({"--help", "--version"}),
        required_any_options=frozenset(
            {"-e", "-i", "-o", "--error", "--input", "--output"}
        ),
    ),
    "sudo": _ExecWrapperGrammar(
        value_options=frozenset(
            {
                "-C",
                "-D",
                "-R",
                "-T",
                "-U",
                "-a",
                "-c",
                "-g",
                "-h",
                "-p",
                "-r",
                "-t",
                "-u",
                "--auth-type",
                "--chdir",
                "--chroot",
                "--close-from",
                "--command-timeout",
                "--group",
                "--host",
                "--login-class",
                "--other-user",
                "--prompt",
                "--role",
                "--type",
                "--user",
            }
        ),
        boolean_options=frozenset(
            {
                "-A",
                "-B",
                "-E",
                "-H",
                "-P",
                "-S",
                "-b",
                "-i",
                "-k",
                "-n",
                "-s",
                "--askpass",
                "--background",
                "--bell",
                "--login",
                "--non-interactive",
                "--preserve-groups",
                "--reset-timestamp",
                "--set-home",
                "--shell",
                "--stdin",
            }
        ),
        detaching_options=frozenset({"-b", "--background"}),
        scope_options=frozenset({"-D", "-R", "-i", "--chdir", "--chroot", "--login"}),
        cwd_value_options=frozenset({"-D", "--chdir"}),
        unknown_cwd_options=frozenset({"-R", "-i", "--chroot", "--login"}),
        optional_inline_value_options=frozenset({"--preserve-env"}),
        preserve_environment_options=frozenset({"-E", "--preserve-env"}),
        short_option_clusters=True,
        command_environment=True,
        scrubs_environment=True,
        terminal_options=frozenset(
            {
                "-K",
                "-V",
                "-e",
                "-l",
                "-v",
                "--edit",
                "--help",
                "--list",
                "--remove-timestamp",
                "--validate",
                "--version",
            }
        ),
    ),
    "timeout": _ExecWrapperGrammar(
        value_options=frozenset({"-k", "-s", "--kill-after", "--signal"}),
        boolean_options=frozenset(
            {"-v", "--foreground", "--preserve-status", "--verbose"}
        ),
        terminal_options=frozenset({"--help", "--version"}),
        positional_operands=1,
    ),
}

# xargs appends stdin-derived arguments, so a direct `xargs gh ...` command is
# incomplete and stays untracked; a shell-wrapped `xargs bash -c 'gh ...'`
# carries its full gh command inline and is scanned.
SHELL_ONLY_EXEC_WRAPPERS = {
    "xargs": _ExecWrapperGrammar(
        value_options=frozenset(
            {
                "-E",
                "-I",
                "-L",
                "-P",
                "-a",
                "-d",
                "-n",
                "-s",
                "--arg-file",
                "--delimiter",
                "--max-args",
                "--max-chars",
                "--max-procs",
                "--process-slot-var",
            }
        ),
        boolean_options=frozenset(
            {
                "-0",
                "-o",
                "-p",
                "-r",
                "-t",
                "-x",
                "--exit",
                "--interactive",
                "--no-run-if-empty",
                "--null",
                "--open-tty",
                "--show-limits",
                "--verbose",
            }
        ),
        optional_inline_value_options=frozenset(
            {"-e", "-i", "-l", "--eof", "--max-lines", "--replace"}
        ),
        terminal_options=frozenset({"--help", "--version"}),
        short_option_clusters=True,
    ),
}


def _attached_option(token: str, options: frozenset[str]) -> str | None:
    for option in options:
        if option.startswith("--") and token.startswith(f"{option}="):
            return option
        if len(option) == 2 and token.startswith(option) and token != option:
            return option
    return None


def _attached_option_argument(token: str, option: str) -> str:
    if option.startswith("--"):
        return token.split("=", 1)[1]
    return token[len(option) :].removeprefix("=")


def _wrapper_value_is_valid(wrapper: str, option: str, value: str) -> bool:
    if not value:
        return False
    if wrapper == "nice" and option in {"-n", "--adjustment"}:
        return re.fullmatch(r"[+-]?\d+", value) is not None
    if wrapper == "timeout" and option in {
        "duration",
        "-k",
        "--kill-after",
    }:
        return (
            re.fullmatch(
                r"[+]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?|inf(?:inity)?)"
                r"(?:[smhd])?",
                value,
                re.I,
            )
            is not None
        )
    if wrapper == "stdbuf" and option in {
        "-e",
        "-i",
        "-o",
        "--error",
        "--input",
        "--output",
    }:
        if value == "L":
            return option not in {"-i", "--input"}
        return (
            re.fullmatch(r"\d+(?:[kKmMgGtTpPeEzZyYrRqQ](?:i?B)?)?", value) is not None
        )
    if wrapper == "xargs" and option in {
        "-L",
        "-P",
        "-l",
        "-n",
        "-s",
        "--max-args",
        "--max-chars",
        "--max-lines",
        "--max-procs",
    }:
        if re.fullmatch(r"\d+", value) is None:
            return False
        if option in {"-P", "--max-procs"}:
            return True
        return int(value) > 0
    return True


def _consume_short_option_cluster(
    token: str,
    tokens: list[str],
    index: int,
    wrapper: str,
    grammar: _ExecWrapperGrammar,
) -> tuple[int, set[str], dict[str, str]] | None:
    if (
        not grammar.short_option_clusters
        or not token.startswith("-")
        or token.startswith("--")
        or len(token) < 3
    ):
        return None
    seen: set[str] = set()
    values: dict[str, str] = {}
    offset = 1
    while offset < len(token):
        option = f"-{token[offset]}"
        if option in grammar.boolean_options:
            seen.add(option)
            offset += 1
            continue
        if option in grammar.value_options:
            value = token[offset + 1 :]
            next_index = index + 1
            if not value:
                if next_index >= len(tokens):
                    return None
                value = tokens[next_index]
                next_index += 1
            if not _wrapper_value_is_valid(wrapper, option, value):
                return None
            seen.add(option)
            values[option] = value
            return next_index, seen, values
        if option in grammar.optional_inline_value_options:
            seen.add(option)
            value = token[offset + 1 :]
            if value:
                if not _wrapper_value_is_valid(wrapper, option, value):
                    return None
                values[option] = value
            return index + 1, seen, values
        return None
    return index + 1, seen, values


def _consume_exec_wrapper(
    tokens: list[str], grammars: dict[str, _ExecWrapperGrammar]
) -> _WrapperConsumption | None:
    """Parse one wrapper prefix without borrowing the following command token."""
    wrapper = Path(tokens[0]).name
    grammar = grammars.get(wrapper)
    if grammar is None:
        return None
    pending_operands = grammar.positional_operands
    seen_options: set[str] = set()
    option_values: dict[str, str] = {}
    command_environment: dict[str, str] = {}
    positional_index = 0
    index = 1
    options_done = False
    while index < len(tokens):
        token = tokens[index]
        if not options_done and token == "--":
            options_done = True
            index += 1
            continue
        if not options_done and token.startswith("-") and token != "-":
            if token in grammar.terminal_options:
                return None
            if token in grammar.nonexecuting_options or _attached_option(
                token, grammar.nonexecuting_options
            ):
                return None
            if token in grammar.value_options:
                if index + 1 >= len(tokens):
                    return None
                value = tokens[index + 1]
                if not _wrapper_value_is_valid(wrapper, token, value):
                    return None
                seen_options.add(token)
                option_values[token] = value
                index += 2
                continue
            attached_value = _attached_option(token, grammar.value_options)
            if attached_value:
                value = _attached_option_argument(token, attached_value)
                if not _wrapper_value_is_valid(wrapper, attached_value, value):
                    return None
                seen_options.add(attached_value)
                option_values[attached_value] = value
                index += 1
                continue
            if token in grammar.optional_inline_value_options:
                seen_options.add(token)
                index += 1
                continue
            attached_optional = _attached_option(
                token, grammar.optional_inline_value_options
            )
            if attached_optional:
                value = _attached_option_argument(token, attached_optional)
                if not _wrapper_value_is_valid(wrapper, attached_optional, value):
                    return None
                seen_options.add(attached_optional)
                option_values[attached_optional] = value
                index += 1
                continue
            if token in grammar.boolean_options:
                seen_options.add(token)
                index += 1
                continue
            cluster = _consume_short_option_cluster(
                token, tokens, index, wrapper, grammar
            )
            if cluster is not None:
                index, cluster_seen, cluster_values = cluster
                seen_options.update(cluster_seen)
                option_values.update(cluster_values)
                continue
            if grammar.numeric_adjustment and re.fullmatch(r"-\d+", token):
                index += 1
                continue
            return None
        if not options_done and grammar.command_environment:
            match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", token, re.S)
            if match:
                command_environment[match.group(1)] = match.group(2)
                index += 1
                continue
        if pending_operands:
            option = (
                "duration" if wrapper == "timeout" and positional_index == 0 else ""
            )
            if option and not _wrapper_value_is_valid(wrapper, option, token):
                return None
            pending_operands -= 1
            positional_index += 1
            index += 1
            continue
        break
    if pending_operands or (
        grammar.required_any_options
        and not grammar.required_any_options.intersection(seen_options)
    ):
        return None
    working_directory_changed = bool(grammar.scope_options.intersection(seen_options))
    working_directory = None
    if not grammar.unknown_cwd_options.intersection(seen_options):
        for option in grammar.cwd_value_options:
            if option in option_values:
                working_directory = option_values[option]
                break
    preserve_all_environment = bool(
        "-E" in seen_options
        or ("--preserve-env" in seen_options and "--preserve-env" not in option_values)
    )
    preserved_environment: set[str] = set()
    preserve_value = option_values.get("--preserve-env")
    if preserve_value:
        preserved_environment.update(
            name.strip() for name in preserve_value.split(",") if name.strip()
        )
    if {"-i", "--login"}.intersection(seen_options):
        preserve_all_environment = False
        preserved_environment.clear()
    return _WrapperConsumption(
        span=index,
        read_success_coupled=(
            (
                not grammar.wait_options
                or bool(grammar.wait_options.intersection(seen_options))
            )
            and not grammar.detaching_options.intersection(seen_options)
        ),
        repository_scope_changed=working_directory_changed,
        working_directory_changed=working_directory_changed,
        working_directory=working_directory,
        command_environment=command_environment,
        scrubs_environment=grammar.scrubs_environment,
        preserve_all_environment=preserve_all_environment,
        preserved_environment=frozenset(preserved_environment),
    )


ENV_VALUE_OPTIONS = frozenset({"-C", "-u", "--chdir", "--unset"})
ENV_OPTIONAL_INLINE_VALUE_OPTIONS = frozenset(
    {"--block-signal", "--default-signal", "--ignore-signal"}
)
ENV_SPLIT_OPTIONS = frozenset({"-S", "--split-string"})
ENV_BOOLEAN_OPTIONS = frozenset(
    {
        "-i",
        "-v",
        "--debug",
        "--ignore-environment",
        "--list-signal-handling",
    }
)
ENV_TERMINAL_OPTIONS = frozenset({"-0", "--help", "--null", "--version"})


def _consume_env_wrapper(tokens: list[str]) -> _EnvConsumption | None:
    if not tokens or Path(tokens[0]).name != "env":
        return None
    environment: dict[str, str] = {}
    unset_variables: set[str] = set()
    clear_environment = False
    repository_scope_changed = False
    working_directory = None
    split_command = None
    index = 1
    options_done = False
    while index < len(tokens):
        token = tokens[index]
        if not options_done and token == "-":
            clear_environment = True
            index += 1
            continue
        if not options_done and token == "--":
            options_done = True
            index += 1
            continue
        if not options_done and token.startswith("-") and token != "-":
            if token in ENV_TERMINAL_OPTIONS:
                return None
            if token in ENV_SPLIT_OPTIONS:
                if index + 1 >= len(tokens):
                    return None
                split_command = tokens[index + 1]
                index += 2
                break
            attached_split = _attached_option(token, ENV_SPLIT_OPTIONS)
            if attached_split:
                split_command = _attached_option_argument(token, attached_split)
                index += 1
                break
            if token in ENV_VALUE_OPTIONS:
                if index + 1 >= len(tokens):
                    return None
                value = tokens[index + 1]
                if token in {"-u", "--unset"}:
                    unset_variables.add(value)
                else:
                    repository_scope_changed = True
                    working_directory = value
                index += 2
                continue
            attached_value = _attached_option(token, ENV_VALUE_OPTIONS)
            if attached_value:
                value = _attached_option_argument(token, attached_value)
                if attached_value in {"-u", "--unset"}:
                    unset_variables.add(value)
                else:
                    repository_scope_changed = True
                    working_directory = value
                index += 1
                continue
            if token in ENV_OPTIONAL_INLINE_VALUE_OPTIONS or _attached_option(
                token, ENV_OPTIONAL_INLINE_VALUE_OPTIONS
            ):
                index += 1
                continue
            if token in ENV_BOOLEAN_OPTIONS:
                if token in {"-i", "--ignore-environment"}:
                    clear_environment = True
                index += 1
                continue
            if token.startswith("-") and not token.startswith("--") and len(token) > 2:
                offset = 1
                cluster_valid = True
                while offset < len(token):
                    option = f"-{token[offset]}"
                    if option == "-0":
                        return None
                    if option in {"-i", "-v"}:
                        if option == "-i":
                            clear_environment = True
                        offset += 1
                        continue
                    if option in {"-C", "-S", "-u"}:
                        value = token[offset + 1 :]
                        next_index = index + 1
                        if not value:
                            if next_index >= len(tokens):
                                return None
                            value = tokens[next_index]
                            next_index += 1
                        if option == "-u":
                            unset_variables.add(value)
                        elif option == "-C":
                            repository_scope_changed = True
                            working_directory = value
                        else:
                            split_command = value
                        index = next_index
                        break
                    cluster_valid = False
                    break
                if not cluster_valid:
                    return None
                if offset >= len(token):
                    index += 1
                if split_command is not None:
                    break
                continue
            return None
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", token, re.S)
        if not match:
            break
        environment[match.group(1)] = match.group(2)
        index += 1
    return _EnvConsumption(
        span=index,
        environment=environment,
        unset_variables=frozenset(unset_variables),
        clear_environment=clear_environment,
        repository_scope_changed=repository_scope_changed,
        working_directory=working_directory,
        split_command=split_command,
    )


def _resolved_working_directory(current: str | None, value: str | None) -> str | None:
    if not value or _dynamic_shell_value(value):
        return None
    if os.path.isabs(value):
        return os.path.normpath(value)
    if current is None:
        return None
    return os.path.normpath(os.path.join(current, value))


def _apply_env_consumption(
    context: _ExecutionContext, consumption: _EnvConsumption
) -> _ExecutionContext:
    environment = dict(context.environment)
    host_environment_reset = context.host_environment_reset
    host_environment_uncertain = context.host_environment_uncertain
    if consumption.clear_environment:
        environment.clear()
        host_environment_reset = True
        host_environment_uncertain = False
    for name in consumption.unset_variables:
        environment.pop(name, None)
        if name == "GH_HOST":
            host_environment_reset = True
            host_environment_uncertain = False
    environment.update(consumption.environment)
    working_directory = context.working_directory
    if consumption.repository_scope_changed:
        working_directory = _resolved_working_directory(
            working_directory, consumption.working_directory
        )
    return _ExecutionContext(
        environment=environment,
        read_success_coupled=context.read_success_coupled,
        repository_scope_changed=(
            context.repository_scope_changed or consumption.repository_scope_changed
        ),
        host_environment_reset=host_environment_reset,
        host_environment_uncertain=host_environment_uncertain,
        working_directory=working_directory,
    )


def _apply_wrapper_consumption(
    context: _ExecutionContext, consumption: _WrapperConsumption
) -> _ExecutionContext:
    environment = dict(context.environment)
    repository_scope_changed = context.repository_scope_changed
    host_environment_reset = context.host_environment_reset
    host_environment_uncertain = context.host_environment_uncertain
    if consumption.scrubs_environment and not consumption.preserve_all_environment:
        preserved = consumption.preserved_environment
        if "GH_REPO" in environment and "GH_REPO" not in preserved:
            environment.pop("GH_REPO", None)
            repository_scope_changed = True
        if "GH_HOST" in environment and "GH_HOST" not in preserved:
            environment.pop("GH_HOST", None)
            host_environment_reset = False
            host_environment_uncertain = True
        environment = {
            name: value for name, value in environment.items() if name in preserved
        }
    command_environment = consumption.command_environment or {}
    environment.update(command_environment)
    if "GH_HOST" in command_environment:
        host_environment_uncertain = False
    working_directory = context.working_directory
    if consumption.working_directory_changed:
        working_directory = _resolved_working_directory(
            working_directory, consumption.working_directory
        )
    return _ExecutionContext(
        environment=environment,
        read_success_coupled=(
            context.read_success_coupled and consumption.read_success_coupled
        ),
        repository_scope_changed=(
            repository_scope_changed or consumption.repository_scope_changed
        ),
        host_environment_reset=host_environment_reset,
        host_environment_uncertain=host_environment_uncertain,
        working_directory=working_directory,
    )


def _inline_environment(
    prefix: list[str], initial: _ExecutionContext | None = None
) -> _ExecutionContext | None:
    remaining = list(prefix)
    context = initial or _ExecutionContext(environment={})
    environment = dict(context.environment)
    index = 0
    while index < len(remaining):
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", remaining[index], re.S)
        if not match:
            break
        environment[match.group(1)] = match.group(2)
        index += 1
    context = _ExecutionContext(
        environment=environment,
        read_success_coupled=context.read_success_coupled,
        repository_scope_changed=context.repository_scope_changed,
        host_environment_reset=context.host_environment_reset,
        host_environment_uncertain=context.host_environment_uncertain,
        working_directory=context.working_directory,
    )
    if index < len(remaining) and remaining[index] in {"command", "exec"}:
        index += 1
    while index < len(remaining):
        token = remaining[index]
        if Path(token).name == "env":
            env_consumption = _consume_env_wrapper(remaining[index:])
            if env_consumption is None or env_consumption.split_command is not None:
                return None
            context = _apply_env_consumption(context, env_consumption)
            index += env_consumption.span
            continue
        consumed = _consume_exec_wrapper(remaining[index:], EXEC_THROUGH_WRAPPERS)
        if consumed is None:
            return None
        context = _apply_wrapper_consumption(context, consumed)
        index += consumed.span
    return context


@dataclass(frozen=True)
class _ShellWord:
    value: str
    unquoted: bool
    command_boundary: bool = False
    assignment: bool = False


def _tokenize_shell_words(command: str) -> list[_ShellWord]:
    """Tokenize enough shell grammar to retain reserved-word quote context."""
    words: list[_ShellWord] = []
    value: list[str] = []
    character_unquoted: list[bool] = []
    active = False
    entirely_unquoted = True
    quoted_before_equals = False
    saw_equals = False
    quote = ""
    case_modes: list[str] = []
    at_command_start = True

    def observe_word(word: _ShellWord) -> None:
        nonlocal at_command_start
        if case_modes and word.unquoted and word.value == "esac":
            case_modes.pop()
            at_command_start = False
            return
        if case_modes and case_modes[-1] == "seek-in":
            if word.unquoted and word.value == "in":
                case_modes[-1] = "pattern"
            return
        if case_modes and case_modes[-1] == "pattern":
            return
        if not at_command_start:
            return
        if word.assignment:
            return
        if word.unquoted and word.value == "case":
            case_modes.append("seek-in")
            at_command_start = False
            return
        command_prefixes = {
            "!",
            "do",
            "elif",
            "else",
            "if",
            "then",
            "time",
            "until",
            "while",
            "{",
        }
        if word.unquoted and word.value in command_prefixes:
            return
        at_command_start = False

    def flush() -> None:
        nonlocal active, entirely_unquoted, quoted_before_equals, saw_equals
        if active:
            text = "".join(value)
            equals = text.find("=")
            assignment = (
                equals > 0
                and character_unquoted[equals]
                and not quoted_before_equals
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text[:equals]) is not None
            )
            word = _ShellWord(text, entirely_unquoted, assignment=assignment)
            words.append(word)
            observe_word(word)
        value.clear()
        character_unquoted.clear()
        active = False
        entirely_unquoted = True
        quoted_before_equals = False
        saw_equals = False

    def append_character(char: str, *, unquoted: bool) -> None:
        nonlocal active, entirely_unquoted, quoted_before_equals, saw_equals
        if not saw_equals and not unquoted:
            quoted_before_equals = True
        value.append(char)
        character_unquoted.append(unquoted)
        active = True
        if not unquoted:
            entirely_unquoted = False
        if char == "=" and not saw_equals:
            saw_equals = True

    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            if char == quote:
                quote = ""
                index += 1
                continue
            if quote == '"' and char == "\\" and index + 1 < len(command):
                index += 1
                char = command[index]
            append_character(char, unquoted=False)
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            active = True
            entirely_unquoted = False
            if not saw_equals:
                quoted_before_equals = True
            index += 1
            continue
        if char == "\\" and index + 1 < len(command):
            if command[index + 1] == "\n":
                index += 2
                continue
            index += 1
            append_character(command[index], unquoted=False)
            index += 1
            continue
        if char in " \t\r":
            flush()
            index += 1
            continue
        if char == "\n":
            flush()
            words.append(_ShellWord("\n", True, True))
            at_command_start = True
            index += 1
            continue
        if case_modes and case_modes[-1] == "pattern" and char == ")":
            flush()
            words.append(_ShellWord(")", True, True))
            case_modes[-1] = "command"
            at_command_start = True
            index += 1
            continue
        if case_modes and case_modes[-1] == "pattern" and char == "|":
            append_character(char, unquoted=True)
            index += 1
            continue
        if char in ";&|":
            flush()
            end = index + 1
            while end < len(command) and command[end] in ";&|":
                end += 1
            punctuation = command[index:end]
            words.append(_ShellWord(punctuation, True, True))
            if (
                case_modes
                and case_modes[-1] == "command"
                and punctuation in {";;", ";&", ";;&"}
            ):
                case_modes[-1] = "pattern"
            at_command_start = True
            index = end
            continue
        append_character(char, unquoted=True)
        index += 1
    flush()
    return words


def _shell_command_argument(tokens: list[str], shell_index: int) -> str | None:
    """Return the command following a shell's effective -c option."""
    value_options = {"-o", "+o", "-O", "+O", "--init-file", "--rcfile"}
    index = shell_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token in value_options:
            index += 2
            continue
        if token.startswith(("-o", "+o", "-O", "+O")) and len(token) > 2:
            index += 1
            continue
        if token.startswith(("--init-file=", "--rcfile=")):
            index += 1
            continue
        if token == "--":
            return None
        if token.startswith("-") and not token.startswith("--") and "c" in token[1:]:
            return tokens[index + 1] if index + 1 < len(tokens) else None
        if token.startswith("-"):
            index += 1
            continue
        return None
    return None


def _inline_shell_environment(
    prefix: list[_ShellWord], initial: _ExecutionContext | None = None
) -> _ExecutionContext | None:
    remaining = list(prefix)
    context = initial or _ExecutionContext(environment={})
    environment = dict(context.environment)
    while remaining and remaining[0].assignment:
        match = re.fullmatch(
            r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", remaining.pop(0).value, re.S
        )
        if match:
            environment[match.group(1)] = match.group(2)
    context = _ExecutionContext(
        environment=environment,
        read_success_coupled=context.read_success_coupled,
        repository_scope_changed=context.repository_scope_changed,
        host_environment_reset=context.host_environment_reset,
        host_environment_uncertain=context.host_environment_uncertain,
        working_directory=context.working_directory,
    )
    shell_builtin_allowed = True
    while True:
        if not remaining:
            return context

        wrapper = Path(remaining[0].value).name
        if wrapper == "env":
            env_consumption = _consume_env_wrapper([word.value for word in remaining])
            if env_consumption is None or env_consumption.split_command is not None:
                return None
            context = _apply_env_consumption(context, env_consumption)
            del remaining[: env_consumption.span]
            shell_builtin_allowed = False
            continue

        if wrapper == "command":
            if not shell_builtin_allowed:
                return None
            remaining.pop(0)
            while remaining and remaining[0].value.startswith("-"):
                token = remaining.pop(0).value
                if token in {"-V", "-v"}:
                    return None
                if token == "--":
                    break
                if token != "-p":
                    return None
            shell_builtin_allowed = False
            continue

        if wrapper == "exec":
            if not shell_builtin_allowed:
                return None
            remaining.pop(0)
            while remaining and remaining[0].value.startswith("-"):
                token = remaining.pop(0).value
                if token == "--":
                    break
                if token == "-a":
                    if not remaining:
                        return None
                    remaining.pop(0)
                    continue
                if token not in {"-c", "-l"}:
                    return None
            shell_builtin_allowed = False
            continue

        consumed = _consume_exec_wrapper(
            [word.value for word in remaining],
            EXEC_THROUGH_WRAPPERS | SHELL_ONLY_EXEC_WRAPPERS,
        )
        if consumed is None:
            return None
        context = _apply_wrapper_consumption(context, consumed)
        del remaining[: consumed.span]
        shell_builtin_allowed = False


def _executable_shell_position(
    words: list[_ShellWord],
    shell_index: int,
    initial: _ExecutionContext | None = None,
) -> _ExecutionContext | None:
    segment_start = 0
    for index in range(shell_index - 1, -1, -1):
        word = words[index]
        if word.command_boundary:
            segment_start = index + 1
            break
    prefix = words[segment_start:shell_index]
    reserved_prefixes = {"!", "do", "elif", "else", "if", "then", "until", "while"}
    changed = True
    while changed:
        changed = False
        while (
            prefix
            and prefix[0].unquoted
            and prefix[0].value in reserved_prefixes | {"time"}
        ):
            reserved = prefix.pop(0).value
            changed = True
            if reserved == "time":
                while prefix and prefix[0].value.startswith("-"):
                    prefix.pop(0)
        if prefix and prefix[0].unquoted and prefix[0].value == "{":
            prefix.pop(0)
            changed = True
    return _inline_shell_environment(prefix, initial)


def _segments_containing_gh(
    command: str,
    *,
    depth: int = 0,
    env_expansion_depth: int = 0,
    read_context_eligible: bool = True,
    initial: _ExecutionContext | None = None,
) -> Iterable[tuple[list[str], bool, _ExecutionContext]]:
    initial = initial or _ExecutionContext(environment={})
    current = initial
    tokens = _tokenize_shell(command)
    if depth < MAX_NESTED_SHELL_DEPTH:
        for substitution in _command_substitutions(command):
            yield from _segments_containing_gh(
                substitution,
                depth=depth + 1,
                env_expansion_depth=env_expansion_depth,
                read_context_eligible=read_context_eligible,
                initial=initial,
            )
        shell_words = _tokenize_shell_words(command)
        shell_tokens = [word.value for word in shell_words]
        for index, word in enumerate(shell_words):
            if Path(word.value).name not in {"bash", "dash", "ksh", "sh", "zsh"}:
                continue
            shell_context = _executable_shell_position(shell_words, index, initial)
            if shell_context is None:
                continue
            nested_command = _shell_command_argument(shell_tokens, index)
            if nested_command is not None:
                yield from _segments_containing_gh(
                    nested_command,
                    depth=depth + 1,
                    env_expansion_depth=env_expansion_depth,
                    read_context_eligible=read_context_eligible,
                    initial=shell_context,
                )
    elif re.search(r"(?:^|[\s;&|(`])(?:[^\s;&|()]*/)?gh(?:\s|$)", command):
        # A pathological wrapper chain should fail closed instead of hiding a
        # command merely because the defensive recursion budget was exhausted.
        yield ["gh", "unknown", "nested-shell"], False, initial
    has_control_operator = any(
        token and set(token) <= {";", "&", "|", "\n"} for token in tokens
    )
    segment: list[str] = []
    for token in tokens + [";"]:
        if token and set(token) <= {";", "&", "|", "\n"}:
            if env_expansion_depth < MAX_NESTED_SHELL_DEPTH:
                for env_index, part in enumerate(segment):
                    if Path(part).name != "env":
                        continue
                    prefix_context = _inline_environment(segment[:env_index], current)
                    if prefix_context is None:
                        continue
                    env_consumption = _consume_env_wrapper(segment[env_index:])
                    if (
                        env_consumption is None
                        or env_consumption.split_command is None
                        or any(
                            marker in env_consumption.split_command
                            for marker in ("$", "`")
                        )
                    ):
                        continue
                    try:
                        split_tokens = shlex.split(env_consumption.split_command)
                    except ValueError:
                        continue
                    split_context = _apply_env_consumption(
                        prefix_context, env_consumption
                    )
                    remainder = segment[env_index + env_consumption.span :]
                    expanded = [*split_tokens, *remainder]
                    if not expanded:
                        continue
                    yield from _segments_containing_gh(
                        shlex.join(["env", *expanded]),
                        depth=depth,
                        env_expansion_depth=env_expansion_depth + 1,
                        read_context_eligible=(
                            read_context_eligible and not has_control_operator
                        ),
                        initial=split_context,
                    )
                    break
            candidates: list[tuple[int, _ExecutionContext]] = []
            for gh_index, part in enumerate(segment):
                if not _gh_token(part):
                    continue
                context = _inline_environment(segment[:gh_index], current)
                if context is not None:
                    candidates.append((gh_index, context))
            if candidates:
                gh_index, context = candidates[0]
                normalized = ["gh"] + segment[gh_index + 1 :]
                if (
                    "GH_REPO" in context.environment
                    and _flag_value(normalized, "--repo", "-R") is None
                ):
                    normalized.extend(["--repo", context.environment["GH_REPO"]])
                if (
                    "GH_HOST" in context.environment
                    and _flag_value(normalized, "--hostname") is None
                ):
                    normalized.extend(["--hostname", context.environment["GH_HOST"]])
                elif (
                    context.host_environment_uncertain
                    and _flag_value(normalized, "--hostname") is None
                ):
                    normalized.extend(["--hostname", WRAPPER_UNKNOWN_HOST_SENTINEL])
                elif (
                    context.host_environment_reset
                    and _flag_value(normalized, "--hostname") is None
                ):
                    normalized.extend(["--hostname", "github.com"])
                read_eligible = (
                    depth == 0
                    and read_context_eligible
                    and not has_control_operator
                    and len(candidates) == 1
                    and context.read_success_coupled
                )
                yield normalized, read_eligible, context
            # A `cd` segment changes the directory the following segments run
            # in, but only when its terminator guarantees it took effect: after
            # `||` the next command runs precisely because the cd failed, and a
            # pipe confines the cd to its own subshell.
            if set(token) <= {";", "\n"} or token == "&&":
                is_cd, cd_directory = _cd_segment_directory(
                    segment, current.working_directory
                )
                if is_cd:
                    if cd_directory is None:
                        current = replace(
                            current,
                            repository_scope_changed=True,
                            working_directory=None,
                        )
                    else:
                        current = replace(
                            current, working_directory=cd_directory
                        )
            segment = []
        else:
            segment.append(token)


def _flag_value(tokens: list[str], *names: str) -> str | None:
    for index, token in enumerate(tokens):
        for name in names:
            if token == name and index + 1 < len(tokens):
                return tokens[index + 1]
            if token.startswith(f"{name}="):
                return token.split("=", 1)[1]
            if len(name) == 2 and token.startswith(name) and token != name:
                return token[len(name) :].removeprefix("=")
    return None


def _flag_values(tokens: list[str], *names: str) -> Iterable[str]:
    for index, token in enumerate(tokens):
        for name in names:
            if token == name and index + 1 < len(tokens):
                yield tokens[index + 1]
            elif token.startswith(f"{name}="):
                yield token.split("=", 1)[1]
            elif len(name) == 2 and token.startswith(name) and token != name:
                yield token[len(name) :].removeprefix("=")


def _read_query_value(value: str, cwd: str | None) -> tuple[str, bool]:
    if not value.startswith("@"):
        # Interpolated text is kept so classification can still spot a
        # top-level mutation keyword, but it is never "known": it cannot
        # authorize a write or bind an exact target.
        return value, "$" not in value and "`" not in value
    if value == "@-":
        return "", False
    path = Path(value[1:])
    if not path.is_absolute():
        if cwd is None:
            return "", False
        path = Path(cwd) / path
    try:
        if path.stat().st_size > 128_000:
            return "", False
        return path.read_text(encoding="utf-8", errors="replace"), True
    except OSError:
        return "", False


def _dynamic_shell_value(value: str | None) -> bool:
    if not value:
        return False
    return bool(re.search(r"\$|`|<\(|>\(|[*?\[]", value))


def _graphql_input_document(
    tokens: list[str], cwd: str | None
) -> tuple[dict[str, Any] | None, bool]:
    input_value = _flag_value(tokens, "--input")
    if not input_value:
        return None, True
    if input_value == "-" or _dynamic_shell_value(input_value):
        return None, False
    path = Path(input_value)
    if not path.is_absolute():
        if cwd is None:
            return None, False
        path = Path(cwd) / path
    try:
        if path.stat().st_size > 128_000:
            return None, False
        document = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None, False
    return (document, True) if isinstance(document, dict) else (None, False)


def _graphql_query_texts(tokens: list[str], cwd: str | None) -> list[tuple[str, bool]]:
    queries: list[tuple[str, bool]] = []
    for field in _flag_values(tokens, "-f", "-F", "--field", "--raw-field"):
        key, separator, value = field.partition("=")
        if separator and key == "query":
            queries.append(_read_query_value(value, cwd))
    if queries:
        return queries

    document, known = _graphql_input_document(tokens, cwd)
    if not known:
        return [("", False)]
    if document is None:
        return []
    query = document.get("query")
    return [(query, True)] if isinstance(query, str) else [("", False)]


def _graphql_operation_name(
    tokens: list[str], cwd: str | None
) -> tuple[str | None, bool]:
    values: list[str] = []
    for field in _flag_values(tokens, "-f", "-F", "--field", "--raw-field"):
        key, separator, value = field.partition("=")
        if separator and key == "operationName":
            resolved, known = _read_query_value(value, cwd)
            if not known:
                return None, False
            values.append(resolved)
    if values:
        return values[-1], True
    document, known = _graphql_input_document(tokens, cwd)
    if not known:
        return None, False
    if document is None or document.get("operationName") is None:
        return None, True
    operation_name = document.get("operationName")
    return (operation_name, True) if isinstance(operation_name, str) else (None, False)


def _graphql_operation_text(query: str) -> str:
    without_block_strings = re.sub(r'""".*?"""', " ", query, flags=re.S)
    without_strings = re.sub(r'"(?:\\.|[^"\\])*"', " ", without_block_strings)
    return re.sub(r"#[^\n]*", " ", without_strings)


def _graphql_operations(query: str) -> list[tuple[str, str | None]]:
    tokens = re.findall(
        r"\$[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*|[{}()\[\]@]",
        _graphql_operation_text(query),
    )
    operations: list[tuple[str, str | None]] = []
    at_definition_boundary = True
    in_header = False
    selection_depth = 0
    parenthesis_depth = 0
    bracket_depth = 0
    for index, token in enumerate(tokens):
        if selection_depth:
            if token == "{":
                selection_depth += 1
            elif token == "}":
                selection_depth -= 1
                if selection_depth == 0:
                    at_definition_boundary = True
            continue

        lowered = token.lower()
        if at_definition_boundary:
            if token == "{":
                operations.append(("query", None))
                selection_depth = 1
                at_definition_boundary = False
            elif lowered in {"mutation", "query", "subscription"}:
                name = None
                if index + 1 < len(tokens) and re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*", tokens[index + 1]
                ):
                    name = tokens[index + 1]
                operations.append((lowered, name))
                at_definition_boundary = False
                in_header = True
                parenthesis_depth = 0
                bracket_depth = 0
            elif lowered == "fragment":
                at_definition_boundary = False
                in_header = True
                parenthesis_depth = 0
                bracket_depth = 0
            continue

        if not in_header:
            continue
        if token == "(":
            parenthesis_depth += 1
        elif token == ")":
            parenthesis_depth = max(0, parenthesis_depth - 1)
        elif token == "[":
            bracket_depth += 1
        elif token == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif token == "{" and parenthesis_depth == 0 and bracket_depth == 0:
            selection_depth = 1
            in_header = False
    return operations or [("query", None)]


def _graphql_operation_kind(query: str, operation_name: str | None = None) -> str:
    operations = _graphql_operations(query)
    if operation_name is not None:
        selected = [kind for kind, name in operations if name == operation_name]
        return selected[0] if len(selected) == 1 else "unknown"
    if len(operations) == 1:
        return operations[0][0]
    # Without an operationName, a multi-operation request should fail at the
    # server. Treat any contained mutation conservatively in case a wrapper
    # supplies selection data outside the visible command.
    return "mutation" if any(kind == "mutation" for kind, _ in operations) else "query"


def _api_endpoint(tokens: list[str]) -> str:
    index = 2
    while index < len(tokens):
        token = tokens[index]
        if token in FLAGS_WITH_VALUES:
            index += 2
            continue
        if any(token.startswith(f"{flag}=") for flag in FLAGS_WITH_VALUES):
            index += 1
            continue
        if any(
            len(flag) == 2 and token.startswith(flag) and token != flag
            for flag in FLAGS_WITH_VALUES
        ):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return ""


def _api_kind(tokens: list[str], cwd: str | None) -> str:
    method_value = _flag_value(tokens, "--method", "-X") or ""
    if _dynamic_shell_value(method_value):
        return "unknown"
    method = method_value.upper()
    endpoint = _api_endpoint(tokens)
    if endpoint == "graphql":
        queries = _graphql_query_texts(tokens, cwd)
        operation_name, operation_name_known = _graphql_operation_name(tokens, cwd)
        if not operation_name_known or any(not known for _, known in queries):
            # Shell interpolation makes the exact request uncertain, but a
            # visible top-level mutation keyword still marks a write so the
            # readback rule tracks it. Anything else stays unknown: it can
            # neither authorize nor count.
            for query, _ in queries:
                if not query:
                    continue
                if operation_name_known:
                    visible_kind = _graphql_operation_kind(query, operation_name)
                    if visible_kind == "mutation":
                        return "write"
                elif any(kind == "mutation" for kind, _ in _graphql_operations(query)):
                    return "write"
            return "unknown"
        if any(
            _graphql_operation_kind(query, operation_name) in {"mutation", "unknown"}
            for query, _ in queries
        ):
            return "write"
        return "read"
    if method in {"POST", "PATCH", "PUT", "DELETE"}:
        return "write"
    if method == "GET":
        return "read"
    if method:
        return "write"
    if (
        next(
            iter(_flag_values(tokens, "-f", "-F", "--field", "--raw-field", "--input")),
            None,
        )
        is not None
    ):
        return "write"
    return "read"


def _graphql_fields(tokens: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for field in _flag_values(tokens, "-f", "-F", "--field", "--raw-field"):
        key, separator, value = field.partition("=")
        if separator and key != "query":
            fields[key] = value
    return fields


def _target_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _graphql_bound_target_fields(tokens: list[str], cwd: str | None) -> set[str]:
    queries = _graphql_query_texts(tokens, cwd)
    if len(queries) != 1 or not queries[0][1]:
        return set()
    query = queries[0][0]
    operations = _graphql_operations(query)
    if len(operations) != 1:
        return set()
    operation_name, operation_name_known = _graphql_operation_name(tokens, cwd)
    if not operation_name_known:
        return set()
    if operation_name is not None and operations[0][1] != operation_name:
        return set()
    operation_text = _graphql_operation_text(query)
    bound_fields = {
        key
        for key in {
            "pullRequestId",
            "issueId",
            "subjectId",
            "repositoryId",
            "id",
        }
        if re.search(rf"\b{re.escape(key)}\s*:\s*\${re.escape(key)}\b", operation_text)
    }
    repository_call = re.search(
        r"\brepository\s*\((?=[^)]*\bowner\s*:\s*\$owner\b)"
        r"(?=[^)]*\bname\s*:\s*\$name\b)[^)]*\)",
        operation_text,
        re.S,
    )
    if repository_call:
        bound_fields.update({"owner", "name"})
        if re.search(
            r"\b(?:pullRequest|issue|issueOrPullRequest)\s*\("
            r"[^)]*\bnumber\s*:\s*\$number\b[^)]*\)",
            operation_text,
            re.S,
        ):
            bound_fields.add("number")
    return bound_fields


def _graphql_target(
    tokens: list[str], cwd: str | None, repo: str
) -> tuple[str, str, str]:
    fields = _graphql_fields(tokens)
    bound_fields = _graphql_bound_target_fields(tokens, cwd)
    owner, name = fields.get("owner"), fields.get("name")
    bound_repo = (
        owner
        and name
        and {"owner", "name"} <= bound_fields
        and not owner.startswith("@")
        and not name.startswith("@")
        and not any(char in owner + name for char in "$`")
    )
    if bound_repo:
        repo = f"{owner}/{name}"
    for key in ("pullRequestId", "issueId", "subjectId", "repositoryId", "id"):
        value = fields.get(key)
        if (
            key in bound_fields
            and value
            and not value.startswith("@")
            and not any(char in value for char in "$`")
        ):
            return repo, f"graphql-node:{_target_digest(value)}", f"{repo}:graphql-node"
    queries = _graphql_query_texts(tokens, cwd)
    known_queries = [query for query, known in queries if known]
    scope = (
        "\n".join(known_queries) if len(known_queries) == len(queries) else "unknown"
    )
    operation_name, operation_name_known = _graphql_operation_name(tokens, cwd)
    selection = operation_name if operation_name_known else "unknown"
    scope = f"{scope}\noperationName:{selection or '<unspecified>'}"
    return repo, f"graphql:{_target_digest(scope)}", f"{repo}:graphql"


def _positional_candidates(tokens: list[str], group: str, action: str) -> list[str]:
    candidates: list[str] = []
    boolean_flags = GH_ACTION_BOOLEAN_FLAGS.get((group, action), set())
    value_flags = (
        GH_VALUE_FLAGS | GH_ACTION_VALUE_FLAGS.get((group, action), set())
    ) - boolean_flags
    index = 3
    while index < len(tokens):
        token = tokens[index]
        if token in value_flags:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        candidates.append(token)
        index += 1
    return candidates


def _immediate_target(tokens: list[str], group: str, action: str) -> str | None:
    if action not in TARGETED_ACTIONS.get(group, set()):
        return None
    candidates = _positional_candidates(tokens, group, action)
    for candidate in candidates:
        if re.search(r"https?://", candidate):
            return candidate
    if group in {"pr", "issue"}:
        # Prefer a definite number so an unrecognized value flag's argument
        # ("--json state 11") cannot displace the numbered target.
        for candidate in candidates:
            if re.fullmatch(r"\d+", candidate):
                return candidate
    return candidates[0] if candidates else None


def _operation_has_dynamic_scope(tokens: list[str]) -> bool:
    explicit_repo = _flag_value(tokens, "--repo", "-R")
    if _dynamic_shell_value(explicit_repo):
        return True
    group = tokens[1] if len(tokens) > 1 else "unknown"
    action = tokens[2] if len(tokens) > 2 else ""
    if group == "api":
        if _dynamic_shell_value(_api_endpoint(tokens)):
            return True
        if _api_endpoint(tokens) == "graphql":
            target_fields = _graphql_fields(tokens)
            return any(
                target_fields.get(key, "").startswith("@")
                or _dynamic_shell_value(target_fields.get(key))
                for key in (
                    "owner",
                    "name",
                    "number",
                    "pullRequestId",
                    "issueId",
                    "subjectId",
                    "repositoryId",
                    "id",
                )
            )
        return False
    return _dynamic_shell_value(_immediate_target(tokens, group, action))


def _has_explicit_repository_scope(tokens: list[str], cwd: str | None) -> bool:
    explicit_repo = _flag_value(tokens, "--repo", "-R")
    if explicit_repo and not _dynamic_shell_value(explicit_repo):
        return True
    group = tokens[1] if len(tokens) > 1 else "unknown"
    action = tokens[2] if len(tokens) > 2 else ""
    if group == "api":
        endpoint = _api_endpoint(tokens)
        if re.search(r"(?:^|/)repos/[^/$`{}:]+/[^/$`{}:]+(?:/|$)", endpoint):
            return True
        if endpoint == "graphql":
            fields = _graphql_fields(tokens)
            bound_fields = _graphql_bound_target_fields(tokens, cwd)
            if (
                {"owner", "name"} <= bound_fields
                and fields.get("owner")
                and fields.get("name")
                and not fields["owner"].startswith("@")
                and not fields["name"].startswith("@")
                and not _dynamic_shell_value(fields["owner"] + fields["name"])
            ):
                return True
            return any(
                key in bound_fields
                and bool(fields.get(key))
                and not fields[key].startswith("@")
                and not _dynamic_shell_value(fields[key])
                for key in (
                    "pullRequestId",
                    "issueId",
                    "subjectId",
                    "repositoryId",
                    "id",
                )
            )
        return False
    target = _immediate_target(tokens, group, action)
    if group == "repo" and target and "/" in target:
        return not _dynamic_shell_value(target)
    return bool(
        target
        and re.search(r"https?://[^/]+/[^/]+/[^/]+/", target)
        and not _dynamic_shell_value(target)
    )


def _repo_and_target(tokens: list[str], cwd: str | None) -> tuple[str, str, str]:
    explicit_repo = _flag_value(tokens, "--repo", "-R")
    if _dynamic_shell_value(explicit_repo):
        return (
            "unknown-dynamic-repo",
            "dynamic:repository",
            "dynamic GitHub repository target",
        )
    repo = _normalize_repo(explicit_repo) if explicit_repo else _repo_from_cwd(cwd)
    group = tokens[1] if len(tokens) > 1 else "unknown"
    action = tokens[2] if len(tokens) > 2 else ""

    if group == "api":
        endpoint = _api_endpoint(tokens)
        if _dynamic_shell_value(endpoint):
            return repo, "dynamic:api", f"{repo}:dynamic API target"
        if endpoint == "graphql":
            return _graphql_target(tokens, cwd, repo)
        match = re.search(r"repos/([^/]+/[^/]+)/(pulls|issues)/(\d+)", endpoint)
        if match:
            repo, resource, number = match.groups()
            object_kind = "pull" if resource == "pulls" else "issue-or-pull"
            return repo, f"{object_kind}:number:{number}", f"{repo}#{number}"
        repo_match = re.search(r"repos/([^/]+/[^/]+)", endpoint)
        if repo_match:
            repo = repo_match.group(1)
        normalized_endpoint = endpoint.split("?", 1)[0].strip("/") or "unknown"
        category_match = re.search(r"repos/[^/]+/[^/]+/([^/]+)", normalized_endpoint)
        category = category_match.group(1) if category_match else "api"
        return (
            repo,
            f"api:{_target_digest(normalized_endpoint)}",
            f"{repo}:api:{category}",
        )

    target = _immediate_target(tokens, group, action)
    if _dynamic_shell_value(target):
        return repo, f"dynamic:{group}", f"{repo}:{group}:dynamic target"
    if group == "repo" and target and "/" in target:
        repo = _normalize_repo(target)
        return repo, "repo", f"{repo}:repo"
    if target and group in {"pr", "issue"}:
        url_match = re.search(r"github\.com/([^/]+/[^/]+)/(pull|issues)/(\d+)", target)
        if url_match:
            repo, url_kind, target = url_match.groups()
            object_kind = "pull" if url_kind == "pull" else "issue"
        else:
            object_kind = "pull" if group == "pr" else "issue"
        if re.fullmatch(r"\d+", target):
            return repo, f"{object_kind}:number:{target}", f"{repo}#{target}"
    if target:
        label = f"{repo}:{group}"
        if group not in {"secret", "variable"}:
            label = f"{label}:{target}"
        return repo, f"{group}:{_target_digest(target)}", label
    return (
        repo,
        f"{group}:{action or 'unknown'}",
        f"{repo}:{group}:{action or 'unknown'}",
    )


def classify_gh_operations(command: str, cwd: str) -> list[GhOperation]:
    operations: list[GhOperation] = []
    ambient_environment = {
        name: os.environ[name] for name in ("GH_HOST", "GH_REPO") if name in os.environ
    }
    initial_context = _ExecutionContext(
        environment=ambient_environment,
        working_directory=os.path.abspath(cwd),
    )
    for tokens, read_eligible, context in _segments_containing_gh(
        command, initial=initial_context
    ):
        if len(tokens) < 2:
            continue
        operation_cwd = context.working_directory
        if (
            context.repository_scope_changed
            and "GH_REPO" not in context.environment
            and not _has_explicit_repository_scope(tokens, operation_cwd)
        ):
            tokens = [*tokens, "--repo", WRAPPER_CWD_SENTINEL]
        group = tokens[1]
        action = tokens[2] if len(tokens) > 2 else ""
        if group in IGNORED_GROUPS:
            continue
        if group == "api":
            kind = _api_kind(tokens, operation_cwd)
        elif group == "repo" and action == "set-default" and "--view" in tokens[3:]:
            # `gh repo set-default --view` only prints the pinned repository;
            # the shared conventions prescribe it as a read-only probe.
            kind = "read"
        elif action in WRITE_ACTIONS.get(group, set()):
            kind = "write"
        elif action in READ_ACTIONS.get(group, set()):
            kind = "read"
        else:
            kind = "unknown"
        dynamic_scope = _operation_has_dynamic_scope(tokens)
        repo, target, label = _repo_and_target(tokens, operation_cwd)
        hostname = _flag_value(tokens, "--hostname") or os.environ.get(
            "GH_HOST", "github.com"
        )
        normalized_host = hostname.strip().lower() or "unknown-host"
        repo_key = f"github:{normalized_host}:{repo}"
        explicit_scope = _has_explicit_repository_scope(tokens, operation_cwd)
        operations.append(
            GhOperation(
                kind=kind,
                workflow_key=f"{repo_key}:{target}",
                workflow_label=label,
                repo_key=repo_key,
                summary=f"gh {group} {action}".strip(),
                read_eligible=(
                    kind == "read"
                    and read_eligible
                    and explicit_scope
                    and not dynamic_scope
                    and not _dynamic_shell_value(hostname)
                ),
            )
        )
    return operations


def _creation_group(operation: GhOperation) -> str | None:
    for group in ("pr", "issue"):
        if (
            operation.summary == f"gh {group} create"
            and operation.workflow_key == f"{operation.repo_key}:{group}:create"
        ):
            return group
    return None


def _creation_preflight(read: GhOperation) -> GhOperation | None:
    for group in ("pr", "issue"):
        suffix = f":{group}:list"
        if read.summary != f"gh {group} list" or not read.workflow_label.endswith(
            suffix
        ):
            continue
        return GhOperation(
            kind="read",
            workflow_key=f"{read.repo_key}:{group}:create",
            workflow_label=f"{read.workflow_label.removesuffix(suffix)}:{group}:create",
            repo_key=read.repo_key,
            summary=read.summary,
            read_eligible=True,
        )
    return None


def _bounded_tool_response_text(payload: dict[str, Any]) -> str:
    """Return a bounded transient view of tool output; never persist it."""
    stack: list[tuple[Any, int]] = [(payload.get("tool_response"), 0)]
    fragments: list[str] = []
    remaining = MAX_TOOL_RESPONSE_SCAN_CHARS
    visited = 0
    while stack and remaining > 0 and visited < 128:
        value, depth = stack.pop()
        visited += 1
        if isinstance(value, str):
            fragment = value[:remaining]
            fragments.append(fragment)
            remaining -= len(fragment)
        elif depth < 4 and isinstance(value, dict):
            for index, item in enumerate(value.values()):
                if index >= 64:
                    break
                stack.append((item, depth + 1))
        elif depth < 4 and isinstance(value, list):
            stack.extend((item, depth + 1) for item in reversed(value[:64]))
    return "\n".join(fragments)


def _created_target_from_response(
    payload: dict[str, Any], operation: GhOperation
) -> GhOperation | None:
    group = _creation_group(operation)
    if group is None or not operation.repo_key.startswith("github:"):
        return None
    host_and_repo = operation.repo_key.removeprefix("github:")
    if ":" not in host_and_repo:
        return None
    host, repo = host_and_repo.rsplit(":", 1)
    if _dynamic_shell_value(host) or _dynamic_shell_value(repo) or "/" not in repo:
        return None

    text = _bounded_tool_response_text(payload).replace("\\/", "/")
    urls = {
        (url_host.lower(), owner.lower(), name.lower(), resource.lower(), number)
        for url_host, owner, name, resource, number in re.findall(
            r"https?://([^/\s\"'<>]+)/([^/\s\"'<>]+)/([^/\s\"'<>]+)"
            r"/(pull|issues)/(\d+)(?=$|[/?#\s\"'<>])",
            text,
            flags=re.I,
        )
    }
    if len(urls) != 1:
        return None
    url_host, owner, name, resource, number = next(iter(urls))
    expected_resource = "pull" if group == "pr" else "issues"
    expected_owner, expected_name = repo.lower().split("/", 1)
    if (
        url_host != host.lower()
        or (owner, name) != (expected_owner, expected_name)
        or resource != expected_resource
    ):
        return None
    object_kind = "pull" if group == "pr" else "issue"
    return GhOperation(
        kind="write",
        workflow_key=f"{operation.repo_key}:{object_kind}:number:{number}",
        workflow_label=f"{repo}#{number}",
        repo_key=operation.repo_key,
        summary=operation.summary,
    )


def _activity(
    connection: sqlite3.Connection,
    session_id: str,
    turn_id: str,
    workflow_key: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM hook_activity
        WHERE session_id = ? AND turn_id = ? AND workflow_key = ?
        """,
        (session_id, turn_id, workflow_key),
    ).fetchone()


def _upsert_activity(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
    operation: GhOperation,
    preflight_seen: int | None = None,
    pending_write: int | None = None,
    pending_summary: str | None = None,
) -> None:
    now = isoformat(utc_now())
    with _write_transaction(connection):
        connection.execute(
            """
            INSERT INTO hook_activity (
                session_id, turn_id, workflow_key, workflow_label, repo_key,
                preflight_seen, pending_write, pending_summary, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, turn_id, workflow_key) DO UPDATE SET
                workflow_label = excluded.workflow_label,
                repo_key = excluded.repo_key,
                preflight_seen = CASE WHEN ? IS NULL THEN hook_activity.preflight_seen ELSE ? END,
                pending_write = CASE WHEN ? IS NULL THEN hook_activity.pending_write ELSE ? END,
                pending_summary = CASE WHEN ? IS NULL THEN hook_activity.pending_summary ELSE ? END,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                turn_id,
                operation.workflow_key,
                operation.workflow_label,
                operation.repo_key,
                preflight_seen or 0,
                pending_write or 0,
                pending_summary or "",
                now,
                preflight_seen,
                preflight_seen,
                pending_write,
                pending_write,
                pending_summary,
                pending_summary,
            ),
        )


def _increment_create_attempt(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
    operation: GhOperation,
) -> None:
    row = _activity(connection, session_id, turn_id, operation.workflow_key)
    pending_count = int(row["pending_count"]) if row is not None else 0
    if row is not None and row["pending_write"] and pending_count == 0:
        # Rows created by an older runner predate pending_count. Treat a
        # pending legacy create as one outstanding attempt before adding this
        # one, so mixed-version operation cannot erase it.
        pending_count = 1
    _upsert_activity(
        connection,
        session_id=session_id,
        turn_id=turn_id,
        operation=operation,
        preflight_seen=0,
        pending_write=1,
        pending_summary=operation.summary,
    )
    connection.execute(
        """
        UPDATE hook_activity
        SET pending_count = ?, updated_at = ?
        WHERE session_id = ? AND turn_id = ? AND workflow_key = ?
        """,
        (
            pending_count + 1,
            isoformat(utc_now()),
            session_id,
            turn_id,
            operation.workflow_key,
        ),
    )


def _consume_create_attempt(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
    operation: GhOperation,
) -> None:
    row = _activity(connection, session_id, turn_id, operation.workflow_key)
    if row is None or not row["pending_write"]:
        return
    pending_count = int(row["pending_count"])
    if pending_count <= 0:
        pending_count = 1
    if pending_count == 1:
        connection.execute(
            """
            DELETE FROM hook_activity
            WHERE session_id = ? AND turn_id = ? AND workflow_key = ?
            """,
            (session_id, turn_id, operation.workflow_key),
        )
        return
    connection.execute(
        """
        UPDATE hook_activity
        SET pending_count = ?, preflight_seen = 0, updated_at = ?
        WHERE session_id = ? AND turn_id = ? AND workflow_key = ?
        """,
        (
            pending_count - 1,
            isoformat(utc_now()),
            session_id,
            turn_id,
            operation.workflow_key,
        ),
    )


def _pending_for_turn(
    connection: sqlite3.Connection, session_id: str, turn_id: str
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT * FROM hook_activity
        WHERE session_id = ? AND turn_id = ? AND pending_write = 1
        ORDER BY workflow_label
        """,
        (session_id, turn_id),
    ).fetchall()


def _pending_for_session(
    connection: sqlite3.Connection, session_id: str
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT * FROM hook_activity
        WHERE session_id = ? AND pending_write = 1
        ORDER BY turn_id, workflow_label
        """,
        (session_id,),
    ).fetchall()


def _structured_failure(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.replace("-", "_").lower()
            if normalized in {"interrupted", "is_interrupt", "iserror", "is_error"}:
                if item is True:
                    return True
            elif normalized in {"success", "ok"} and item is False:
                return True
            elif normalized in {"exit_code", "exitcode"} and item is not None:
                try:
                    if int(item) != 0:
                        return True
                except (TypeError, ValueError):
                    return True
            elif normalized == "status" and str(item).lower() in {
                "cancelled",
                "error",
                "failed",
                "failure",
                "interrupted",
            }:
                return True
            elif normalized == "error" and bool(item):
                return True
            if _structured_failure(item):
                return True
        return False
    if isinstance(value, list):
        return any(_structured_failure(item) for item in value)
    if isinstance(value, str):
        return bool(
            re.search(
                r"(?im)^(?:process\s+)?(?:exited with code|exit code|exit_code)"
                r"[=: ]+[1-9]\d*\s*$",
                value.strip(),
            )
        )
    return False


def _successful_response(payload: dict[str, Any], agent: str) -> bool:
    event = str(payload.get("hook_event_name") or "")
    if event == "PostToolUseFailure":
        return False
    response = payload.get("tool_response")
    if response is None:
        return False
    if agent == "claude":
        return not _structured_failure(
            {
                "interrupted": (
                    response.get("interrupted") if isinstance(response, dict) else None
                ),
                "is_interrupt": payload.get("is_interrupt"),
            }
        )
    top_level_outcome = {
        key: payload.get(key)
        for key in (
            "error",
            "exit_code",
            "exitCode",
            "interrupted",
            "is_error",
            "isError",
            "is_interrupt",
            "ok",
            "status",
            "success",
        )
        if key in payload
    }
    return not _structured_failure(
        {"top_level_outcome": top_level_outcome, "response": response}
    )


def _payload_context(payload: dict[str, Any]) -> tuple[str, str, str]:
    session_id = _runtime_id("session", payload.get("session_id") or "unknown-session")
    cwd = str(payload.get("cwd") or os.getcwd())
    event = str(payload.get("hook_event_name") or "")
    return session_id, cwd, event


def _execution_scope(payload: dict[str, Any]) -> str:
    agent_id = payload.get("agent_id")
    return _runtime_id("agent", agent_id) if agent_id else "root"


def _current_epoch_turn(connection: sqlite3.Connection, session_id: str) -> str:
    now = isoformat(utc_now())
    with _write_transaction(connection):
        connection.execute(
            """
            INSERT OR IGNORE INTO hook_sessions (session_id, epoch, updated_at)
            VALUES (?, 0, ?)
            """,
            (session_id, now),
        )
    row = connection.execute(
        "SELECT epoch FROM hook_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return f"epoch:{row['epoch']}"


def _advance_session_epoch(connection: sqlite3.Connection, session_id: str) -> None:
    now = isoformat(utc_now())
    with _write_transaction(connection):
        connection.execute(
            """
            INSERT INTO hook_sessions (session_id, epoch, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                epoch = hook_sessions.epoch + 1,
                updated_at = excluded.updated_at
            """,
            (session_id, now),
        )


def _tool_use_id(payload: dict[str, Any]) -> str:
    value = payload.get("tool_use_id")
    return _runtime_id("tool", value) if value else ""


def _remember_tool_turn(
    connection: sqlite3.Connection,
    session_id: str,
    tool_use_id: str,
    turn_id: str,
) -> None:
    if not tool_use_id:
        return
    with _write_transaction(connection):
        connection.execute(
            """
            INSERT INTO hook_tools (session_id, tool_use_id, turn_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id, tool_use_id) DO UPDATE SET
                turn_id = excluded.turn_id,
                updated_at = excluded.updated_at
            """,
            (session_id, tool_use_id, turn_id, isoformat(utc_now())),
        )


def _forget_tool(connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
    session_id, _, _ = _payload_context(payload)
    tool_use_id = _tool_use_id(payload)
    if not tool_use_id:
        return
    with _write_transaction(connection):
        connection.execute(
            "DELETE FROM hook_tools WHERE session_id = ? AND tool_use_id = ?",
            (session_id, tool_use_id),
        )


def _turn_id(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    remember_tool: bool = False,
) -> str:
    session_id, _, event = _payload_context(payload)
    tool_use_id = _tool_use_id(payload)
    if tool_use_id and event in {"PostToolUse", "PostToolUseFailure"}:
        mapped = connection.execute(
            """
            SELECT turn_id FROM hook_tools
            WHERE session_id = ? AND tool_use_id = ?
            """,
            (session_id, tool_use_id),
        ).fetchone()
        if mapped:
            return str(mapped["turn_id"])

    if payload.get("turn_id"):
        base_turn_id = _runtime_id("turn", payload["turn_id"])
    elif payload.get("prompt_id"):
        base_turn_id = _runtime_id("prompt", payload["prompt_id"])
    else:
        base_turn_id = _current_epoch_turn(connection, session_id)
    turn_id = f"{_execution_scope(payload)}:{base_turn_id}"
    if remember_tool:
        _remember_tool_turn(connection, session_id, tool_use_id, turn_id)
    return turn_id


def _has_tool_mapping(connection: sqlite3.Connection, payload: dict[str, Any]) -> bool:
    session_id, _, _ = _payload_context(payload)
    tool_use_id = _tool_use_id(payload)
    if not tool_use_id:
        return False
    return (
        connection.execute(
            """
            SELECT 1 FROM hook_tools
            WHERE session_id = ? AND tool_use_id = ?
            """,
            (session_id, tool_use_id),
        ).fetchone()
        is not None
    )


def _completed_tool_event(
    connection: sqlite3.Connection, session_id: str, tool_use_id: str
) -> bool:
    if not tool_use_id:
        return False
    return (
        connection.execute(
            """
            SELECT 1 FROM hook_completed_tools
            WHERE session_id = ? AND tool_use_id = ?
            """,
            (session_id, tool_use_id),
        ).fetchone()
        is not None
    )


def _mark_tool_event_completed(
    connection: sqlite3.Connection, session_id: str, tool_use_id: str
) -> None:
    if not tool_use_id:
        return
    connection.execute(
        """
        INSERT INTO hook_completed_tools (session_id, tool_use_id, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(session_id, tool_use_id) DO UPDATE SET
            updated_at = excluded.updated_at
        """,
        (session_id, tool_use_id, isoformat(utc_now())),
    )


def _command_from_payload(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    return str(tool_input.get("command") or tool_input.get("cmd") or "")


def _pre_tool_use(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    agent: str,
    mode: str,
) -> dict[str, Any] | None:
    session_id, cwd, _ = _payload_context(payload)
    writes = [
        op
        for op in classify_gh_operations(_command_from_payload(payload), cwd)
        if op.kind == "write"
    ]
    revision = skill_revision() if writes else ""
    with _write_transaction(connection):
        # A still-running pre-upgrade hook can write raw identifiers after
        # connect-time migration. Absorb them under the same writer lock as
        # this event so its state transition cannot race past pending work.
        _migrate_legacy_hook_state(connection)
        turn_id = _turn_id(connection, payload, remember_tool=True)
        violations = [
            op
            for op in writes
            if not (
                _activity(connection, session_id, turn_id, op.workflow_key)
                or {"preflight_seen": 0}
            )["preflight_seen"]
        ]
        denied = mode == "enforce" and bool(violations)
        outcome = "prevented" if denied else "escaped"
        for operation in violations:
            record_encounter(
                connection,
                rule_id="GH-LIVE-STATE-001",
                workflow_id=operation.workflow_key,
                workflow_label=operation.workflow_label,
                agent=agent,
                outcome=outcome,
                revision=revision,
                detail="GitHub write attempted without a separate successful live-state read.",
            )
        if not denied:
            violation_keys = {operation.workflow_key for operation in violations}
            for operation in writes:
                if operation.workflow_key not in violation_keys:
                    record_encounter(
                        connection,
                        rule_id="GH-LIVE-STATE-001",
                        workflow_id=operation.workflow_key,
                        workflow_label=operation.workflow_label,
                        agent=agent,
                        outcome="passed",
                        revision=revision,
                        detail="Separate live-state read observed before the write attempt.",
                    )
                if _creation_group(operation) is not None:
                    _increment_create_attempt(
                        connection,
                        session_id=session_id,
                        turn_id=turn_id,
                        operation=operation,
                    )
                else:
                    _upsert_activity(
                        connection,
                        session_id=session_id,
                        turn_id=turn_id,
                        operation=operation,
                        preflight_seen=0,
                        pending_write=1,
                        pending_summary=operation.summary,
                    )
    if not violations:
        return None
    labels = ", ".join(sorted({operation.workflow_label for operation in violations}))
    reason = f"Run and inspect a separate live-state read before writing to {labels}."
    if mode == "enforce":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    warning = f"SECQUOIA audit ({INSTALLATION_ID}): {reason}"
    if agent == "codex":
        return {"systemMessage": warning}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": warning,
        }
    }


def _post_tool_use(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    agent: str,
) -> list[str]:
    session_id, cwd, _ = _payload_context(payload)
    operations = classify_gh_operations(_command_from_payload(payload), cwd)
    reads = [
        operation
        for operation in operations
        if operation.kind == "read" and operation.read_eligible
    ]
    writes = [operation for operation in operations if operation.kind == "write"]
    creation_writes = [write for write in writes if _creation_group(write) is not None]
    successful = _successful_response(payload, agent)
    revision = skill_revision() if successful and operations else ""
    with _write_transaction(connection):
        _migrate_legacy_hook_state(connection)
        tool_use_id = _tool_use_id(payload)
        if creation_writes and _completed_tool_event(
            connection, session_id, tool_use_id
        ):
            _forget_tool(connection, payload)
            return []
        has_tool_mapping = _has_tool_mapping(connection, payload)
        correlated = (
            agent != "claude"
            or bool(payload.get("turn_id") or payload.get("prompt_id"))
            or has_tool_mapping
        )
        turn_id = _turn_id(connection, payload)
        if not successful:
            for write in writes:
                if _creation_group(write) is not None and not has_tool_mapping:
                    _increment_create_attempt(
                        connection,
                        session_id=session_id,
                        turn_id=turn_id,
                        operation=write,
                    )
                else:
                    _upsert_activity(
                        connection,
                        session_id=session_id,
                        turn_id=turn_id,
                        operation=write,
                        preflight_seen=0,
                        pending_write=1,
                        pending_summary=write.summary,
                    )
            labels = sorted({write.workflow_label for write in writes})
            if creation_writes:
                _mark_tool_event_completed(connection, session_id, tool_use_id)
            _forget_tool(connection, payload)
            return labels

        if not correlated:
            reads = []
        resolved_writes = list(writes)
        creation_indexes = [
            index
            for index, write in enumerate(writes)
            if _creation_group(write) is not None
        ]
        if has_tool_mapping and len(creation_indexes) == 1:
            create_index = creation_indexes[0]
            resolved_writes[create_index] = (
                _created_target_from_response(payload, writes[create_index])
                or writes[create_index]
            )
        for original, resolved in zip(writes, resolved_writes, strict=True):
            if original.workflow_key != resolved.workflow_key:
                _consume_create_attempt(
                    connection,
                    session_id=session_id,
                    turn_id=turn_id,
                    operation=original,
                )
        writes = resolved_writes
        pending_before = (
            _pending_for_session(connection, session_id)
            if agent == "codex"
            else _pending_for_turn(connection, session_id, turn_id)
        )
        for read in reads:
            _upsert_activity(
                connection,
                session_id=session_id,
                turn_id=turn_id,
                operation=read,
                preflight_seen=1,
            )
            create_preflight = _creation_preflight(read)
            if create_preflight is not None:
                pending_create = connection.execute(
                    """
                    SELECT 1 FROM hook_activity
                    WHERE session_id = ? AND turn_id = ? AND workflow_key = ?
                      AND pending_write = 1
                    """,
                    (session_id, turn_id, create_preflight.workflow_key),
                ).fetchone()
                if pending_create is None:
                    _upsert_activity(
                        connection,
                        session_id=session_id,
                        turn_id=turn_id,
                        operation=create_preflight,
                        preflight_seen=1,
                    )

        for pending in pending_before:
            matching_read = next(
                (
                    read
                    for read in reads
                    if read.workflow_key == pending["workflow_key"]
                ),
                None,
            )
            if matching_read:
                pending_operation = GhOperation(
                    kind="write",
                    workflow_key=pending["workflow_key"],
                    workflow_label=pending["workflow_label"],
                    repo_key=pending["repo_key"],
                    summary=pending["pending_summary"],
                )
                _upsert_activity(
                    connection,
                    session_id=session_id,
                    turn_id=str(pending["turn_id"]),
                    operation=pending_operation,
                    pending_write=0,
                    pending_summary="",
                )
                record_encounter(
                    connection,
                    rule_id="GH-WRITE-READBACK-001",
                    workflow_id=pending["workflow_key"],
                    workflow_label=pending["workflow_label"],
                    agent=agent,
                    outcome="passed",
                    revision=revision,
                    detail="Separate post-write readback observed.",
                )

        for write in writes:
            if _creation_group(write) is not None and not has_tool_mapping:
                _increment_create_attempt(
                    connection,
                    session_id=session_id,
                    turn_id=turn_id,
                    operation=write,
                )
            else:
                _upsert_activity(
                    connection,
                    session_id=session_id,
                    turn_id=turn_id,
                    operation=write,
                    preflight_seen=0,
                    pending_write=1,
                    pending_summary=write.summary,
                )
        if creation_writes:
            _mark_tool_event_completed(connection, session_id, tool_use_id)
        _forget_tool(connection, payload)
        return []


def _clear_turn_state(
    connection: sqlite3.Connection, session_id: str, turn_id: str
) -> None:
    with _write_transaction(connection):
        connection.execute(
            "DELETE FROM hook_activity WHERE session_id = ? AND turn_id = ?",
            (session_id, turn_id),
        )
        connection.execute(
            "DELETE FROM hook_tools WHERE session_id = ? AND turn_id = ?",
            (session_id, turn_id),
        )


def _finalize_session_activity(
    connection: sqlite3.Connection,
    session_id: str,
    *,
    agent: str,
    detail: str,
    clear_tools: bool,
    clear_session: bool = False,
    revision: str | None = None,
) -> list[str]:
    current_revision = revision or skill_revision()
    with _write_transaction(connection):
        _migrate_legacy_hook_state(connection)
        pending = connection.execute(
            """
            SELECT * FROM hook_activity
            WHERE session_id = ? AND pending_write = 1
            ORDER BY turn_id, workflow_label
            """,
            (session_id,),
        ).fetchall()
        for row in pending:
            record_encounter(
                connection,
                rule_id="GH-WRITE-READBACK-001",
                workflow_id=row["workflow_key"],
                workflow_label=row["workflow_label"],
                agent=agent,
                outcome="escaped",
                revision=current_revision,
                detail=detail,
            )
        connection.execute(
            "DELETE FROM hook_activity WHERE session_id = ?", (session_id,)
        )
        if clear_tools:
            connection.execute(
                "DELETE FROM hook_tools WHERE session_id = ?", (session_id,)
            )
        if clear_session:
            connection.execute(
                "DELETE FROM hook_sessions WHERE session_id = ?", (session_id,)
            )
    return sorted({str(row["workflow_label"]) for row in pending})


def _stop(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    agent: str,
    mode: str,
) -> dict[str, Any]:
    session_id, _, _ = _payload_context(payload)
    revision = skill_revision()
    with _write_transaction(connection):
        _migrate_legacy_hook_state(connection)
        turn_id = _turn_id(connection, payload)
        pending = (
            _pending_for_session(connection, session_id)
            if agent == "codex"
            else _pending_for_turn(connection, session_id, turn_id)
        )
        if not pending:
            if agent == "codex":
                connection.execute(
                    "DELETE FROM hook_activity WHERE session_id = ?", (session_id,)
                )
                connection.execute(
                    "DELETE FROM hook_tools WHERE session_id = ?", (session_id,)
                )
            else:
                _clear_turn_state(connection, session_id, turn_id)
            return {}

        # Block at most once per stop attempt: stop_hook_active marks the
        # re-entry after a prior block, and blocking again would loop an agent
        # that cannot perform the readback (for example, gh became
        # unavailable). The re-entry downgrades to an escape with an advisory.
        already_continued = bool(payload.get("stop_hook_active"))
        should_block = mode == "enforce" and not already_continued
        outcome = "prevented" if should_block else "escaped"
        for row in pending:
            record_encounter(
                connection,
                rule_id="GH-WRITE-READBACK-001",
                workflow_id=row["workflow_key"],
                workflow_label=row["workflow_label"],
                agent=agent,
                outcome=outcome,
                revision=revision,
                detail="Turn stopped with an unverified GitHub write.",
            )
        if not should_block:
            if agent == "codex":
                connection.execute(
                    "DELETE FROM hook_activity WHERE session_id = ?", (session_id,)
                )
                connection.execute(
                    "DELETE FROM hook_tools WHERE session_id = ?", (session_id,)
                )
            else:
                _clear_turn_state(connection, session_id, turn_id)
    labels = ", ".join(row["workflow_label"] for row in pending)
    reason = f"Re-read and verify the GitHub write to {labels} before finishing."
    if should_block:
        return {"decision": "block", "reason": reason}
    return {"systemMessage": f"SECQUOIA audit ({INSTALLATION_ID}): {reason}"}


def _user_prompt_submit(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    agent: str,
) -> dict[str, Any] | None:
    session_id, _, _ = _payload_context(payload)
    revision = skill_revision()
    # Rotation and cleanup are one serialized boundary transition.
    with _write_transaction(connection):
        _migrate_legacy_hook_state(connection)
        _advance_session_epoch(connection, session_id)
        labels = _finalize_session_activity(
            connection,
            session_id,
            agent=agent,
            detail=(
                "A new user turn began with an unverified GitHub write from the "
                "previous turn."
            ),
            clear_tools=False,
            revision=revision,
        )
    if not labels:
        return None
    targets = ", ".join(labels)
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                f"SECQUOIA audit ({INSTALLATION_ID}): The previous turn ended "
                f"with an unverified GitHub write to {targets}. Re-read it before "
                "relying on its outcome."
            ),
        }
    }


def _session_start(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    agent: str,
) -> dict[str, Any] | None:
    if str(payload.get("source") or "").lower() == "compact":
        return None
    session_id, _, _ = _payload_context(payload)
    labels = _finalize_session_activity(
        connection,
        session_id,
        agent=agent,
        detail="A session boundary was reached with an unverified GitHub write.",
        clear_tools=True,
        clear_session=True,
    )
    if not labels:
        return None
    targets = ", ".join(labels)
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                f"SECQUOIA audit ({INSTALLATION_ID}): Recovered an unverified "
                f"GitHub write to {targets}. Re-read it before relying on its outcome."
            ),
        }
    }


def _finalize_nonblocking_boundary(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    agent: str,
    detail: str,
    clear_session: bool = False,
) -> None:
    session_id, _, _ = _payload_context(payload)
    _finalize_session_activity(
        connection,
        session_id,
        agent=agent,
        detail=detail,
        clear_tools=True,
        clear_session=clear_session,
    )


def run_hook(
    payload: dict[str, Any],
    *,
    agent: str,
    mode: str,
    explicit_state_dir: str | None = None,
) -> dict[str, Any] | None:
    connection = connect_database(explicit_state_dir)
    try:
        _, _, event = _payload_context(payload)
        if event == "SessionStart":
            return _session_start(connection, payload, agent=agent)
        if event == "UserPromptSubmit":
            return _user_prompt_submit(connection, payload, agent=agent)
        if event == "PreToolUse":
            return _pre_tool_use(connection, payload, agent=agent, mode=mode)
        if event == "PostToolUse":
            _post_tool_use(connection, payload, agent=agent)
            return None
        if event == "PostToolUseFailure":
            labels = _post_tool_use(connection, payload, agent=agent)
            if not labels:
                return None
            targets = ", ".join(labels)
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUseFailure",
                    "additionalContext": (
                        f"SECQUOIA audit ({INSTALLATION_ID}): The failed command "
                        f"may have written to {targets}. Perform an exact readback "
                        "before relying on its outcome."
                    ),
                }
            }
        if event in {"Stop", "SubagentStop"}:
            return _stop(connection, payload, agent=agent, mode=mode)
        if event == "StopFailure":
            _finalize_nonblocking_boundary(
                connection,
                payload,
                agent=agent,
                detail="The turn failed with an unverified GitHub write.",
            )
            return None
        if event == "SessionEnd":
            _finalize_nonblocking_boundary(
                connection,
                payload,
                agent=agent,
                detail="The session ended with an unverified GitHub write.",
                clear_session=True,
            )
            return None
        return None
    finally:
        connection.close()


def _owned_handler(handler: Any) -> bool:
    return isinstance(handler, dict) and INSTALLATION_ID in str(
        handler.get("command", "")
    )


def _remove_owned_hooks(document: dict[str, Any]) -> bool:
    changed = False
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept_groups.append(group)
                continue
            handlers = [
                handler for handler in group["hooks"] if not _owned_handler(handler)
            ]
            if len(handlers) != len(group["hooks"]):
                changed = True
            if handlers:
                updated = dict(group)
                updated["hooks"] = handlers
                kept_groups.append(updated)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    return changed


def _atomic_json_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=False)
            handle.write("\n")
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _load_hook_document(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{path}: 'hooks' must be a JSON object")
    return document


def _load_hooks(path: Path) -> dict[str, Any]:
    return _load_hook_document(
        path, {"description": "User lifecycle hooks.", "hooks": {}}
    )


def _backup_if_present(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    shutil.copy2(path, backup)
    return backup


def install_codex_hooks(
    codex_home: Path, script: Path, mode: str
) -> tuple[Path, Path | None]:
    hooks_path = codex_home / "hooks.json"
    document = _load_hooks(hooks_path)
    _remove_owned_hooks(document)
    command = (
        f"/usr/bin/python3 {shlex.quote(str(script))} hook --agent codex "
        f"--mode {mode} --installation-id {INSTALLATION_ID}"
    )
    handler = {
        "type": "command",
        "command": command,
        "timeout": 5,
        "statusMessage": "Checking SECQUOIA workflow invariants",
    }
    hooks = document["hooks"]
    for event in ("PreToolUse", "PostToolUse"):
        hooks.setdefault(event, []).append(
            {"matcher": "^Bash$", "hooks": [dict(handler)]}
        )
    boundary_handler = dict(handler)
    boundary_handler.pop("statusMessage", None)
    hooks.setdefault("SessionStart", []).append(
        {"matcher": "startup|resume|clear", "hooks": [dict(boundary_handler)]}
    )
    for event in ("UserPromptSubmit", "Stop"):
        hooks.setdefault(event, []).append({"hooks": [dict(boundary_handler)]})
    rendered = json.dumps(document, indent=2, sort_keys=False) + "\n"
    if hooks_path.exists() and hooks_path.read_text(encoding="utf-8") == rendered:
        return hooks_path, None
    backup = _backup_if_present(hooks_path)
    _atomic_json_write(hooks_path, document)
    return hooks_path, backup


def install_claude_hooks(
    settings_path: Path, script: Path, mode: str
) -> tuple[Path, Path | None]:
    # Claude Code reads lifecycle hooks from settings.json alongside unrelated
    # user settings, so only the "hooks" key may change. Handlers omit the
    # Codex-only statusMessage field; the timeout is in seconds for both tools.
    document = _load_hook_document(settings_path, {"hooks": {}})
    _remove_owned_hooks(document)
    command = (
        f"/usr/bin/python3 {shlex.quote(str(script))} hook --agent claude "
        f"--mode {mode} --installation-id {INSTALLATION_ID}"
    )
    handler = {"type": "command", "command": command, "timeout": 5}
    hooks = document["hooks"]
    for event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        hooks.setdefault(event, []).append(
            {"matcher": "Bash", "hooks": [dict(handler)]}
        )
    hooks.setdefault("SessionStart", []).append(
        {"matcher": "startup|resume|clear|fork", "hooks": [dict(handler)]}
    )
    for event in (
        "UserPromptSubmit",
        "Stop",
        "SubagentStop",
        "StopFailure",
        "SessionEnd",
    ):
        hooks.setdefault(event, []).append({"hooks": [dict(handler)]})
    rendered = json.dumps(document, indent=2, sort_keys=False) + "\n"
    if settings_path.exists() and settings_path.read_text(encoding="utf-8") == rendered:
        return settings_path, None
    backup = _backup_if_present(settings_path)
    _atomic_json_write(settings_path, document)
    return settings_path, backup


def uninstall_claude_hooks(settings_path: Path) -> tuple[Path, Path | None, bool]:
    if not settings_path.exists():
        return settings_path, None, False
    document = _load_hook_document(settings_path, {"hooks": {}})
    changed = _remove_owned_hooks(document)
    if not changed:
        return settings_path, None, False
    if document.get("hooks") == {}:
        del document["hooks"]
    backup = _backup_if_present(settings_path)
    _atomic_json_write(settings_path, document)
    return settings_path, backup, True


def uninstall_codex_hooks(codex_home: Path) -> tuple[Path, Path | None, bool]:
    hooks_path = codex_home / "hooks.json"
    if not hooks_path.exists():
        return hooks_path, None, False
    document = _load_hooks(hooks_path)
    changed = _remove_owned_hooks(document)
    if not changed:
        return hooks_path, None, False
    backup = _backup_if_present(hooks_path)
    _atomic_json_write(hooks_path, document)
    return hooks_path, backup, True


def _command_record(args: argparse.Namespace) -> int:
    connection = connect_database(args.state_dir)
    try:
        identifier = record_encounter(
            connection,
            rule_id=args.rule_id,
            workflow_id=args.workflow_id,
            workflow_label=args.workflow_label or args.workflow_id,
            agent=args.agent,
            outcome=args.outcome,
            revision=args.skill_revision or skill_revision(),
            detail=args.detail,
            dedupe_hours=args.dedupe_hours,
        )
    finally:
        connection.close()
    print(identifier)
    return 0


def _command_report(args: argparse.Namespace) -> int:
    with report_database(args.state_dir) as connection:
        if connection is None:
            rows = []
        else:
            rows = report_encounters(
                connection,
                since_days=args.since_days,
                min_encounters=args.min_encounters,
            )
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print(
            f"No recurring candidates: fewer than {args.min_encounters} independent "
            f"violations per rule in the last {args.since_days} days."
        )
        return 0
    for row in rows:
        print(
            f"{row['rule_id']} [{row['skill']}]: {row['violations']} violations "
            f"across {row['distinct_targets']} targets / {row['opportunities']} opportunities "
            f"({row['prevented']} prevented, {row['escaped']} escaped); "
            f"agents={','.join(row['agents'])}; {row['description']}"
        )
    return 0


def _command_hook(args: argparse.Namespace) -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        print(f"invalid hook JSON: {error}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print("hook input must be a JSON object", file=sys.stderr)
        return 1
    output = run_hook(
        payload,
        agent=args.agent,
        mode=args.mode,
        explicit_state_dir=args.state_dir,
    )
    if output is not None:
        print(json.dumps(output, separators=(",", ":")))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser(
        "record", help="record one rule opportunity or violation"
    )
    record.add_argument("--rule-id", required=True, choices=sorted(RULES))
    record.add_argument("--workflow-id", required=True)
    record.add_argument("--workflow-label")
    record.add_argument("--agent", required=True)
    record.add_argument("--outcome", required=True, choices=sorted(OUTCOME_RANK))
    record.add_argument("--skill-revision")
    record.add_argument("--detail", default="")
    record.add_argument("--dedupe-hours", type=int, default=DEFAULT_DEDUPE_HOURS)
    record.add_argument("--state-dir")
    record.set_defaults(function=_command_record)

    report = subparsers.add_parser(
        "report", help="show rules eligible for lessons review"
    )
    report.add_argument("--since-days", type=int, default=DEFAULT_REPORT_DAYS)
    report.add_argument("--min-encounters", type=int, default=DEFAULT_MIN_ENCOUNTERS)
    report.add_argument("--state-dir")
    report.add_argument("--json", action="store_true")
    report.set_defaults(function=_command_report)

    hook = subparsers.add_parser(
        "hook", help="consume one Codex or Claude hook event from stdin"
    )
    hook.add_argument("--agent", required=True)
    hook.add_argument("--mode", choices=("audit", "enforce"), default="audit")
    hook.add_argument("--state-dir")
    hook.add_argument(
        "--installation-id", default=INSTALLATION_ID, help=argparse.SUPPRESS
    )
    hook.set_defaults(function=_command_hook)

    install = subparsers.add_parser(
        "install-codex-hooks", help="merge Codex hook handlers"
    )
    install.add_argument("--codex-home", type=Path, required=True)
    install.add_argument("--script", type=Path, default=Path(__file__).resolve())
    install.add_argument("--mode", choices=("audit", "enforce"), default="audit")

    def command_install(args: argparse.Namespace) -> int:
        path, backup = install_codex_hooks(args.codex_home, args.script, args.mode)
        message = f"Installed Codex encounter hooks in {path} ({args.mode} mode)."
        if backup:
            message += f" Previous file backed up to {backup}."
        print(message)
        return 0

    install.set_defaults(function=command_install)

    uninstall = subparsers.add_parser(
        "uninstall-codex-hooks", help="remove owned Codex handlers"
    )
    uninstall.add_argument("--codex-home", type=Path, required=True)

    def command_uninstall(args: argparse.Namespace) -> int:
        path, backup, changed = uninstall_codex_hooks(args.codex_home)
        if changed:
            print(f"Removed Codex encounter hooks from {path}; backup: {backup}.")
        else:
            print(f"No SECQUOIA encounter hooks found in {path}.")
        return 0

    uninstall.set_defaults(function=command_uninstall)

    claude_install = subparsers.add_parser(
        "install-claude-hooks", help="merge Claude Code hook handlers"
    )
    claude_install.add_argument(
        "--settings-path",
        type=Path,
        default=Path.home() / ".claude" / "settings.json",
    )
    claude_install.add_argument("--script", type=Path, default=Path(__file__).resolve())
    claude_install.add_argument("--mode", choices=("audit", "enforce"), default="audit")

    def command_install_claude(args: argparse.Namespace) -> int:
        path, backup = install_claude_hooks(args.settings_path, args.script, args.mode)
        message = f"Installed Claude encounter hooks in {path} ({args.mode} mode)."
        if backup:
            message += f" Previous file backed up to {backup}."
        print(message)
        return 0

    claude_install.set_defaults(function=command_install_claude)

    claude_uninstall = subparsers.add_parser(
        "uninstall-claude-hooks", help="remove owned Claude Code handlers"
    )
    claude_uninstall.add_argument(
        "--settings-path",
        type=Path,
        default=Path.home() / ".claude" / "settings.json",
    )

    def command_uninstall_claude(args: argparse.Namespace) -> int:
        path, backup, changed = uninstall_claude_hooks(args.settings_path)
        if changed:
            print(f"Removed Claude encounter hooks from {path}; backup: {backup}.")
        else:
            print(f"No SECQUOIA encounter hooks found in {path}.")
        return 0

    claude_uninstall.set_defaults(function=command_uninstall_claude)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.function(args))


if __name__ == "__main__":
    raise SystemExit(main())
