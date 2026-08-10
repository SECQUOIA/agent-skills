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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


INSTALLATION_ID = "secquoia-encounter-ledger"
DEFAULT_DEDUPE_HOURS = 24
DEFAULT_REPORT_DAYS = 30
DEFAULT_MIN_ENCOUNTERS = 3
HOOK_STATE_RETENTION_DAYS = 30
HOOK_SCHEMA_VERSION = 1
MAX_NESTED_SHELL_DEPTH = 32
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
    """Replace pre-hashing lifecycle identifiers without losing pending state."""
    rows = connection.execute("SELECT * FROM hook_activity").fetchall()
    legacy_rows = [
        row
        for row in rows
        if not _current_runtime_id(str(row["session_id"]))
        or not _current_turn_id(str(row["turn_id"]))
    ]
    if not legacy_rows:
        connection.execute(f"PRAGMA user_version = {HOOK_SCHEMA_VERSION}")
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
            turn_id = "root:epoch:0"
        else:
            turn_id = f"root:{_runtime_id('turn', raw_turn)}"
        connection.execute(
            """
            INSERT INTO hook_activity (
                session_id, turn_id, workflow_key, workflow_label, repo_key,
                preflight_seen, pending_write, pending_summary, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, turn_id, workflow_key) DO UPDATE SET
                workflow_label = excluded.workflow_label,
                repo_key = excluded.repo_key,
                preflight_seen = MAX(
                    hook_activity.preflight_seen, excluded.preflight_seen
                ),
                pending_write = MAX(
                    hook_activity.pending_write, excluded.pending_write
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
    connection.execute(f"PRAGMA user_version = {HOOK_SCHEMA_VERSION}")


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
        """
    )
    stale_cutoff = isoformat(utc_now() - timedelta(days=HOOK_STATE_RETENTION_DAYS))
    with _write_transaction(connection):
        _migrate_legacy_hook_state(connection)
        for table in ("hook_activity", "hook_tools", "hook_sessions"):
            connection.execute(
                f"DELETE FROM {table} WHERE updated_at < ?", (stale_cutoff,)
            )
    return connection


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


def _repo_from_cwd(cwd: str) -> str:
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


def _inline_environment(prefix: list[str]) -> tuple[dict[str, str], bool]:
    remaining = list(prefix)
    if remaining and remaining[0] in {"command", "env"}:
        remaining.pop(0)
    environment: dict[str, str] = {}
    for token in remaining:
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", token, re.S)
        if not match:
            return {}, False
        environment[match.group(1)] = match.group(2)
    return environment, True


def _segments_containing_gh(
    command: str, *, depth: int = 0
) -> Iterable[tuple[list[str], bool]]:
    tokens = _tokenize_shell(command)
    if depth < MAX_NESTED_SHELL_DEPTH:
        for substitution in _command_substitutions(command):
            yield from _segments_containing_gh(substitution, depth=depth + 1)
        for index, token in enumerate(tokens[:-2]):
            if Path(token).name in {"bash", "dash", "ksh", "sh", "zsh"}:
                option = tokens[index + 1]
                if option.startswith("-") and "c" in option[1:]:
                    yield from _segments_containing_gh(
                        tokens[index + 2], depth=depth + 1
                    )
    elif re.search(r"(?:^|[\s;&|(`])(?:[^\s;&|()]*/)?gh(?:\s|$)", command):
        # A pathological wrapper chain should fail closed instead of hiding a
        # command merely because the defensive recursion budget was exhausted.
        yield ["gh", "unknown", "nested-shell"], False
    has_control_operator = any(
        token and set(token) <= {";", "&", "|", "\n"} for token in tokens
    )
    gh_count = sum(1 for token in tokens if _gh_token(token))
    segment: list[str] = []
    for token in tokens + [";"]:
        if token and set(token) <= {";", "&", "|", "\n"}:
            gh_index = next(
                (index for index, part in enumerate(segment) if _gh_token(part)), None
            )
            if gh_index is not None:
                inline_environment, executable_prefix = _inline_environment(
                    segment[:gh_index]
                )
                if not executable_prefix:
                    segment = []
                    continue
                normalized = ["gh"] + segment[gh_index + 1 :]
                if "GH_REPO" in inline_environment:
                    normalized.extend(["--repo", inline_environment["GH_REPO"]])
                if "GH_HOST" in inline_environment:
                    normalized.extend(["--hostname", inline_environment["GH_HOST"]])
                read_eligible = (
                    depth == 0 and not has_control_operator and gh_count == 1
                )
                yield normalized, read_eligible
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


def _read_query_value(value: str, cwd: str) -> tuple[str, bool]:
    if not value.startswith("@"):
        return ("", False) if "$" in value or "`" in value else (value, True)
    if value == "@-":
        return "", False
    path = Path(value[1:])
    if not path.is_absolute():
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
    tokens: list[str], cwd: str
) -> tuple[dict[str, Any] | None, bool]:
    input_value = _flag_value(tokens, "--input")
    if not input_value:
        return None, True
    if input_value == "-" or _dynamic_shell_value(input_value):
        return None, False
    path = Path(input_value)
    if not path.is_absolute():
        path = Path(cwd) / path
    try:
        if path.stat().st_size > 128_000:
            return None, False
        document = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None, False
    return (document, True) if isinstance(document, dict) else (None, False)


def _graphql_query_texts(tokens: list[str], cwd: str) -> list[tuple[str, bool]]:
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


def _graphql_operation_name(tokens: list[str], cwd: str) -> tuple[str | None, bool]:
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
        r"[A-Za-z_][A-Za-z0-9_]*|[{}()]", _graphql_operation_text(query)
    )
    operations: list[tuple[str, str | None]] = []
    depth = 0
    for index, token in enumerate(tokens):
        if token == "{":
            if depth == 0 and not operations:
                operations.append(("query", None))
            depth += 1
        elif token == "}":
            depth = max(0, depth - 1)
        elif depth == 0 and token.lower() in {"mutation", "query", "subscription"}:
            name = None
            if index + 1 < len(tokens) and re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", tokens[index + 1]
            ):
                name = tokens[index + 1]
            operations.append((token.lower(), name))
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


def _api_kind(tokens: list[str], cwd: str) -> str:
    method_value = _flag_value(tokens, "--method", "-X") or ""
    if _dynamic_shell_value(method_value):
        return "unknown"
    method = method_value.upper()
    endpoint = _api_endpoint(tokens)
    if endpoint == "graphql":
        queries = _graphql_query_texts(tokens, cwd)
        operation_name, operation_name_known = _graphql_operation_name(tokens, cwd)
        if not operation_name_known or any(not known for _, known in queries):
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


def _graphql_bound_target_fields(tokens: list[str], cwd: str) -> set[str]:
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


def _graphql_target(tokens: list[str], cwd: str, repo: str) -> tuple[str, str, str]:
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


def _immediate_target(tokens: list[str], group: str, action: str) -> str | None:
    if action not in TARGETED_ACTIONS.get(group, set()) or len(tokens) < 4:
        return None
    candidate = tokens[3]
    return None if candidate.startswith("-") else candidate


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


def _has_explicit_repository_scope(tokens: list[str], cwd: str) -> bool:
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


def _repo_and_target(tokens: list[str], cwd: str) -> tuple[str, str, str]:
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
    for tokens, read_eligible in _segments_containing_gh(command):
        if len(tokens) < 2:
            continue
        group = tokens[1]
        action = tokens[2] if len(tokens) > 2 else ""
        if group in IGNORED_GROUPS:
            continue
        if group == "api":
            kind = _api_kind(tokens, cwd)
        elif action in WRITE_ACTIONS.get(group, set()):
            kind = "write"
        elif action in READ_ACTIONS.get(group, set()):
            kind = "read"
        else:
            kind = "unknown"
        dynamic_scope = _operation_has_dynamic_scope(tokens)
        repo, target, label = _repo_and_target(tokens, cwd)
        hostname = _flag_value(tokens, "--hostname") or os.environ.get(
            "GH_HOST", "github.com"
        )
        normalized_host = hostname.strip().lower() or "unknown-host"
        repo_key = f"github:{normalized_host}:{repo}"
        explicit_scope = _has_explicit_repository_scope(tokens, cwd)
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
    successful = _successful_response(payload, agent)
    revision = skill_revision() if successful and operations else ""
    with _write_transaction(connection):
        correlated = (
            agent != "claude"
            or bool(payload.get("turn_id") or payload.get("prompt_id"))
            or _has_tool_mapping(connection, payload)
        )
        turn_id = _turn_id(connection, payload)
        if not successful:
            for write in writes:
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
            _forget_tool(connection, payload)
            return labels

        if not correlated:
            reads = []
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
            _upsert_activity(
                connection,
                session_id=session_id,
                turn_id=turn_id,
                operation=write,
                preflight_seen=0,
                pending_write=1,
                pending_summary=write.summary,
            )
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

        should_block = mode == "enforce"
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
    connection = connect_database(args.state_dir)
    try:
        rows = report_encounters(
            connection,
            since_days=args.since_days,
            min_encounters=args.min_encounters,
        )
    finally:
        connection.close()
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
