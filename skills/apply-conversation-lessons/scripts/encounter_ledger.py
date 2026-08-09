#!/usr/bin/env python3
"""Shared encounter ledger and lifecycle-hook adapter for SECQUOIA skills.

The ledger stores only rule identifiers, workflow labels, agent names, outcomes,
and skill revisions. It never reads or persists prompts or transcripts.
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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


INSTALLATION_ID = "secquoia-encounter-ledger"
DEFAULT_DEDUPE_HOURS = 24
DEFAULT_REPORT_DAYS = 30
DEFAULT_MIN_ENCOUNTERS = 3
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
    "pr": {"checks", "diff", "list", "status", "view"},
    "issue": {"list", "status", "view"},
    "repo": {"list", "view"},
    "run": {"list", "view", "watch"},
    "release": {"list", "view"},
    "workflow": {"list", "view"},
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
        "edit",
        "lock",
        "reopen",
        "transfer",
        "unlock",
    },
    "release": {"create", "delete", "edit", "upload"},
    "repo": {"archive", "create", "delete", "edit", "fork", "rename"},
    "workflow": {"disable", "enable", "run"},
    "run": {"cancel", "delete", "rerun"},
    "label": {"clone", "create", "delete", "edit"},
    "secret": {"delete", "set"},
    "variable": {"delete", "set"},
}

FLAGS_WITH_VALUES = {
    "--body",
    "--body-file",
    "--hostname",
    "--input",
    "--jq",
    "--method",
    "--repo",
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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


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
    connection = sqlite3.connect(database, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
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
        """
    )
    return connection


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
    with connection:
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
    rows = connection.execute(
        """
        SELECT
            rule_id,
            COUNT(*) AS opportunities,
            SUM(CASE WHEN outcome != 'passed' THEN 1 ELSE 0 END) AS violations,
            SUM(CASE WHEN outcome = 'prevented' THEN 1 ELSE 0 END) AS prevented,
            SUM(CASE WHEN outcome = 'escaped' THEN 1 ELSE 0 END) AS escaped,
            COUNT(DISTINCT workflow_key) AS distinct_targets,
            GROUP_CONCAT(DISTINCT last_agent) AS agents,
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
                "agents": sorted(filter(None, (row["agents"] or "").split(","))),
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
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return shlex.split(command, posix=False)


def _segments_containing_gh(command: str) -> Iterable[list[str]]:
    tokens = _tokenize_shell(command)
    segment: list[str] = []
    for token in tokens + [";"]:
        if token and set(token) <= {";", "&", "|"}:
            if any(Path(part).name == "gh" for part in segment):
                yield segment
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
    return None


def _read_at_file(value: str | None, cwd: str) -> str:
    if not value or not value.startswith("@"):
        return value or ""
    path = Path(value[1:])
    if not path.is_absolute():
        path = Path(cwd) / path
    try:
        if path.stat().st_size > 128_000:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


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
        if token.startswith("-"):
            index += 1
            continue
        return token
    return ""


def _api_kind(tokens: list[str], cwd: str) -> str:
    method = (_flag_value(tokens, "--method", "-X") or "").upper()
    endpoint = _api_endpoint(tokens)
    if endpoint == "graphql":
        query = _flag_value(tokens, "-f", "-F")
        query_text = _read_at_file(query.split("=", 1)[-1] if query else "", cwd)
        if re.search(r"\bmutation\b", " ".join(tokens) + " " + query_text, re.I):
            return "write"
        return "read"
    if method in {"POST", "PATCH", "PUT", "DELETE"}:
        return "write"
    if method == "GET":
        return "read"
    if any(
        token in {"-f", "-F", "--field", "--raw-field", "--input"} for token in tokens
    ):
        return "write"
    return "read"


def _repo_and_target(tokens: list[str], cwd: str) -> tuple[str, str, str]:
    explicit_repo = _flag_value(tokens, "--repo", "-R")
    repo = _normalize_repo(explicit_repo) if explicit_repo else _repo_from_cwd(cwd)
    group = tokens[1] if len(tokens) > 1 else "unknown"

    if group == "api":
        endpoint = _api_endpoint(tokens)
        match = re.search(r"repos/([^/]+/[^/]+)/(?:pulls|issues)/(\d+)", endpoint)
        if match:
            repo = match.group(1)
            return repo, f"number:{match.group(2)}", f"{repo}#{match.group(2)}"
        repo_match = re.search(r"repos/([^/]+/[^/]+)", endpoint)
        if repo_match:
            repo = repo_match.group(1)
        return repo, "api", f"{repo}:api"

    target = next((token for token in tokens[3:] if re.fullmatch(r"\d+", token)), None)
    if target and group in {"pr", "issue"}:
        return repo, f"number:{target}", f"{repo}#{target}"
    return repo, group, f"{repo}:{group}"


def classify_gh_operations(command: str, cwd: str) -> list[GhOperation]:
    operations: list[GhOperation] = []
    for segment in _segments_containing_gh(command):
        gh_index = next(
            i for i, token in enumerate(segment) if Path(token).name == "gh"
        )
        tokens = segment[gh_index:]
        if len(tokens) < 2:
            continue
        group = tokens[1]
        action = tokens[2] if len(tokens) > 2 else ""
        if group == "api":
            kind = _api_kind(tokens, cwd)
        elif action in WRITE_ACTIONS.get(group, set()):
            kind = "write"
        elif action in READ_ACTIONS.get(group, set()):
            kind = "read"
        else:
            continue
        repo, target, label = _repo_and_target(tokens, cwd)
        repo_key = f"github:{repo}"
        operations.append(
            GhOperation(
                kind=kind,
                workflow_key=f"{repo_key}:{target}",
                workflow_label=label,
                repo_key=repo_key,
                summary=f"gh {group} {action}".strip(),
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
    with connection:
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


def _successful_response(response: Any) -> bool:
    if isinstance(response, dict):
        for key in ("exit_code", "exitCode"):
            if key in response and response[key] is not None:
                return response[key] == 0
        if response.get("isError") is True:
            return False
        return all(_successful_response(value) for value in response.values())
    if isinstance(response, list):
        return all(_successful_response(value) for value in response)
    if isinstance(response, str):
        return (
            re.search(r"(?:exit code|exit_code)[=: ]+[1-9]\d*", response, re.I) is None
        )
    return True


def _hook_context(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    session_id = str(payload.get("session_id") or "unknown-session")
    turn_id = str(payload.get("turn_id") or session_id)
    cwd = str(payload.get("cwd") or os.getcwd())
    event = str(payload.get("hook_event_name") or "")
    return session_id, turn_id, cwd, event


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
    session_id, turn_id, cwd, _ = _hook_context(payload)
    writes = [
        op
        for op in classify_gh_operations(_command_from_payload(payload), cwd)
        if op.kind == "write"
    ]
    violations = [
        op
        for op in writes
        if not (
            _activity(connection, session_id, turn_id, op.workflow_key)
            or {"preflight_seen": 0}
        )["preflight_seen"]
    ]
    if not violations:
        return None
    outcome = "prevented" if mode == "enforce" else "escaped"
    revision = skill_revision()
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
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": f"SECQUOIA audit ({INSTALLATION_ID}): {reason}",
        }
    }


def _post_tool_use(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    agent: str,
) -> None:
    if not _successful_response(payload.get("tool_response")):
        return
    session_id, turn_id, cwd, _ = _hook_context(payload)
    operations = classify_gh_operations(_command_from_payload(payload), cwd)
    reads = [operation for operation in operations if operation.kind == "read"]
    writes = [operation for operation in operations if operation.kind == "write"]
    revision = skill_revision()

    pending_before = _pending_for_turn(connection, session_id, turn_id)
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
                or (read.repo_key == pending["repo_key"] and len(pending_before) == 1)
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
                turn_id=turn_id,
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
        existing = _activity(connection, session_id, turn_id, write.workflow_key)
        if existing and existing["preflight_seen"]:
            record_encounter(
                connection,
                rule_id="GH-LIVE-STATE-001",
                workflow_id=write.workflow_key,
                workflow_label=write.workflow_label,
                agent=agent,
                outcome="passed",
                revision=revision,
                detail="Separate live-state read observed before the write.",
            )
        _upsert_activity(
            connection,
            session_id=session_id,
            turn_id=turn_id,
            operation=write,
            preflight_seen=0,
            pending_write=1,
            pending_summary=write.summary,
        )


def _stop(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    agent: str,
    mode: str,
) -> dict[str, Any]:
    session_id, turn_id, _, _ = _hook_context(payload)
    pending = _pending_for_turn(connection, session_id, turn_id)
    if not pending:
        with connection:
            connection.execute(
                "DELETE FROM hook_activity WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            )
        return {}

    already_continued = bool(payload.get("stop_hook_active"))
    should_block = mode == "enforce" and not already_continued
    outcome = "prevented" if should_block else "escaped"
    revision = skill_revision()
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
    labels = ", ".join(row["workflow_label"] for row in pending)
    reason = f"Re-read and verify the GitHub write to {labels} before finishing."
    if should_block:
        return {"decision": "block", "reason": reason}
    with connection:
        connection.execute(
            "DELETE FROM hook_activity WHERE session_id = ? AND turn_id = ?",
            (session_id, turn_id),
        )
    return {"systemMessage": f"SECQUOIA audit ({INSTALLATION_ID}): {reason}"}


def run_hook(
    payload: dict[str, Any],
    *,
    agent: str,
    mode: str,
    explicit_state_dir: str | None = None,
) -> dict[str, Any] | None:
    connection = connect_database(explicit_state_dir)
    try:
        _, _, _, event = _hook_context(payload)
        if event == "PreToolUse":
            return _pre_tool_use(connection, payload, agent=agent, mode=mode)
        if event == "PostToolUse":
            _post_tool_use(connection, payload, agent=agent)
            return None
        if event == "Stop":
            return _stop(connection, payload, agent=agent, mode=mode)
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
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=False)
            handle.write("\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _load_hooks(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"description": "User lifecycle hooks.", "hooks": {}}
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{path}: 'hooks' must be a JSON object")
    return document


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
    stop_handler = dict(handler)
    stop_handler.pop("statusMessage", None)
    hooks.setdefault("Stop", []).append({"hooks": [stop_handler]})
    rendered = json.dumps(document, indent=2, sort_keys=False) + "\n"
    if hooks_path.exists() and hooks_path.read_text(encoding="utf-8") == rendered:
        return hooks_path, None
    backup = _backup_if_present(hooks_path)
    _atomic_json_write(hooks_path, document)
    return hooks_path, backup


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.function(args))


if __name__ == "__main__":
    raise SystemExit(main())
