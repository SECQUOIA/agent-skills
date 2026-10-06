#!/usr/bin/env python3
"""Read-only integration plan for isolated skill work; never changes Git state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or "Git read failed")
    return result.stdout.rstrip("\n")


def commit(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")


def ancestor(repo: Path, older: str, newer: str) -> bool:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo),
         "merge-base", "--is-ancestor", older, newer], capture_output=True, check=False,
    )
    if result.returncode not in (0, 1):
        raise ValueError("Unable to verify commit ancestry")
    return result.returncode == 0


def active_operation(repo: Path) -> bool:
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        path = Path(git(repo, "rev-parse", "--git-path", name))
        if not path.is_absolute():
            path = repo / path
        if path.exists():
            return True
    return False


def ignored_collisions(repo: Path, result: str) -> list[str]:
    incoming = set(git(repo, "ls-tree", "-r", "--name-only", "-z", result).split("\0")) - {""}
    ignored = set(git(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").split("\0")) - {""}
    collisions = set()
    for path in ignored:
        if path in incoming or any(parent.as_posix() in incoming for parent in Path(path).parents):
            collisions.add(path)
    for path in incoming:
        collisions.update(parent.as_posix() for parent in Path(path).parents
                          if parent.as_posix() in ignored)
    return sorted(collisions)


def plan(repo: Path, branch: str, original: str, upstream: str,
         synced: str, result: str, default_branch: str) -> dict:
    repo = repo.resolve()
    git(repo, "check-ref-format", "--branch", branch)
    git(repo, "check-ref-format", "--branch", default_branch)
    if branch == default_branch:
        raise ValueError("Skill lessons must not integrate into the default branch")
    original, upstream, synced, result = (
        commit(repo, value) for value in (original, upstream, synced, result)
    )
    destination = commit(repo, "refs/heads/" + branch)
    if not ancestor(repo, upstream, synced):
        raise ValueError("Recorded synchronized tip does not contain pinned upstream")
    if not ancestor(repo, synced, result):
        raise ValueError("Result does not descend from recorded synchronized tip")
    lessons = git(repo, "rev-list", "--reverse", synced + ".." + result).splitlines()
    report = {
        "mode": "blocked", "destination_branch": branch,
        "original": original, "upstream": upstream, "synced": synced,
        "result": result, "destination": destination, "lesson_commits": lessons,
        "destination_worktrees": [], "requires_exclusive_access": True,
        "mutations_performed": False,
    }
    # Git's NUL form preserves worktree paths containing whitespace/newlines.
    for block in git(repo, "worktree", "list", "--porcelain", "-z").split("\0\0"):
        fields = dict(field.split(" ", 1) for field in block.split("\0") if " " in field)
        if fields.get("branch") != "refs/heads/" + branch:
            continue
        checkout = Path(fields["worktree"])
        dirty = bool(git(checkout, "status", "--porcelain=v1", "-z", "--untracked-files=all"))
        operation = active_operation(checkout)
        report["destination_worktrees"].append(
            {"path": str(checkout), "dirty": dirty, "operation_in_progress": operation,
             "ignored_collisions": ignored_collisions(checkout, result)}
        )
    if ancestor(repo, result, destination):
        report.update(mode="already_integrated", reason="Result is already in destination history")
    elif destination != original:
        report["reason"] = "Destination advanced; preserve all refs and reinventory concurrent work"
    elif any(w["dirty"] or w["operation_in_progress"] or w["ignored_collisions"]
             for w in report["destination_worktrees"]):
        report["reason"] = "Destination has user work or an existing operation; keep isolated results"
    elif ancestor(repo, destination, result):
        report.update(mode="fast_forward", reason="Destination is an ancestor of the isolated result")
    elif git(repo, "rev-list", "--merges", synced + ".." + result):
        report["reason"] = "New lesson range contains merges; reconcile deliberately, not by bulk cherry-pick"
    else:
        report.update(
            mode="reconcile",
            reason="Synchronization rewrote ancestry; a fast-forward cannot integrate this result",
            next_steps=[
                "Retain original backup, isolated result, and recorded tips",
                "Obtain clean exclusive destination access and recheck its tip",
                "Synchronize destination to pinned upstream using backup and replay verification",
                "Transfer only lesson_commits, inspect conflicts, and verify final tree against result",
                "If access or reconciliation is unavailable, report integration pending without cleanup",
            ],
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--default-branch", required=True)
    for name in ("original", "upstream", "synced", "result"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        report = plan(args.repo, args.branch, args.original, args.upstream,
                      args.synced, args.result, args.default_branch)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))
    return 2 if report["mode"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
