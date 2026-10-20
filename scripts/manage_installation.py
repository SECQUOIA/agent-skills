#!/usr/bin/env python3
"""Install SECQUOIA skills without duplicate discovery or replacing foreign entries.

Fresh default installs use ~/.agents/skills. Existing legacy installs and explicit
custom CODEX_HOME roots keep their location. Hooks always live in CODEX_HOME.
Antigravity skills install to ~/.gemini/config/skills when ~/.gemini exists or
--antigravity-hooks is requested. Copy ownership is recorded per skill; unmarked
copies require manual inspection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


MARKER = ".secquoia-install.json"
INSTALLATION_ID = "secquoia-agent-skills"
IGNORED = {MARKER, ".installed-revision", "__pycache__", ".DS_Store"}


def present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def owned(destination: Path, source: Path) -> bool:
    if destination.is_symlink():
        return destination.resolve() == source.resolve()
    marker = destination / MARKER
    if not destination.is_dir() or not marker.is_file() or marker.is_symlink():
        return False
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
        return value == {
            "installation": INSTALLATION_ID,
            "source": str(source.resolve()),
        }
    except (OSError, ValueError):
        return False


def skills(source_root: Path) -> list[Path]:
    return sorted(
        path for path in source_root.iterdir() if (path / "SKILL.md").is_file()
    )


def retired_entries(root: Path, source_root: Path | list[Path]) -> list[Path]:
    """Recognize only absent source paths with this checkout's exact provenance."""
    if not root.is_dir():
        return []
    roots = [source_root] if isinstance(source_root, Path) else source_root
    return [
        destination
        for destination in sorted(root.iterdir())
        if not any(present(r / destination.name) for r in roots)
        and any(owned(destination, r / destination.name) for r in roots)
    ]


def backup_copy(destination: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = (
        destination.parent.parent / ".secquoia-skill-backups" / stamp / destination.name
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    destination.rename(backup)
    return backup


def prune_retired(root: Path, source_root: Path) -> None:
    for destination in retired_entries(root, source_root):
        if destination.is_symlink():
            destination.unlink()
            print(f"Removed retired owned link: {destination}")
        else:
            # The deleted source cannot prove whether a copied skill has edits.
            # Preserve every owned copy, even when it appears unchanged.
            backup = backup_copy(destination)
            print(f"Preserved retired owned copy in {backup}")


def unique_roots(paths: list[Path]) -> list[Path]:
    result = []
    for path in paths:
        path = path.expanduser().resolve()
        if path not in result:
            result.append(path)
    return result


def codex_root(
    *,
    user_home: Path,
    codex_home: Path,
    sources: list[Path],
    source_root: Path,
    explicit: Path | None,
    custom_home: bool,
) -> tuple[Path, list[Path]]:
    candidates = unique_roots(
        [
            user_home / ".agents" / "skills",
            codex_home / "skills",
            *([explicit] if explicit is not None else []),
        ]
    )
    populated = [
        root
        for root in candidates
        if any(present(root / src.name) for src in sources)
        or retired_entries(root, source_root)
    ]
    if explicit is not None:
        selected = explicit.expanduser().resolve()
    elif len(populated) == 1:
        selected = populated[0]
    else:
        selected = (
            codex_home / "skills" if custom_home else user_home / ".agents" / "skills"
        ).resolve()
    duplicates = [root for root in populated if root != selected]
    if duplicates:
        raise ValueError(
            "Skill names already exist in another Codex discovery root: "
            + ", ".join(str(root) for root in duplicates)
            + ". Inspect those entries and uninstall the owned set before changing roots."
        )
    return selected, candidates


def fingerprint(path: Path) -> str:
    """Compare copy contents, excluding installer bookkeeping and Python caches."""
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        relative = item.relative_to(path)
        if any(part in IGNORED or part.endswith(".pyc") for part in relative.parts):
            continue
        digest.update(str(relative).encode() + b"\0")
        if item.is_symlink():
            digest.update(b"link:" + os.readlink(item).encode())
        elif item.is_file():
            digest.update(b"file:" + item.read_bytes())
        elif item.is_dir():
            digest.update(b"directory")
        else:
            digest.update(b"other")
    return digest.hexdigest()


def installed_revision(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def install_skill(source: Path, root: Path, *, copy: bool, revision: str) -> None:
    destination = root / source.name
    if destination.is_symlink() and not copy:
        return
    if destination.is_dir() and not destination.is_symlink() and copy:
        if fingerprint(destination) == fingerprint(source):
            if source.name == "apply-conversation-lessons":
                (destination / "scripts" / ".installed-revision").write_text(
                    revision + "\n"
                )
            return
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".secquoia-stage-", dir=root.parent
    ) as staging:
        staged = Path(staging) / source.name
        if copy:
            shutil.copytree(
                source,
                staged,
                symlinks=True,
                ignore=shutil.ignore_patterns(*IGNORED, "*.pyc"),
            )
            (staged / MARKER).write_text(
                json.dumps(
                    {
                        "installation": INSTALLATION_ID,
                        "source": str(source.resolve()),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            if source.name == "apply-conversation-lessons":
                (staged / "scripts" / ".installed-revision").write_text(revision + "\n")
        else:
            staged.symlink_to(source.resolve(), target_is_directory=True)
        if destination.is_symlink():
            destination.unlink()
        elif destination.exists():
            # Even owned copies may contain user edits. Keep them outside discovery.
            backup = backup_copy(destination)
            print(f"  Backed up {destination} to {backup}")
        staged.rename(destination)


def run_hooks(
    repo: Path,
    action: str,
    codex_home: Path,
    claude_home: Path,
    codex_skills: Path,
    args: argparse.Namespace,
    *,
    antigravity_home: Path | None = None,
    antigravity_skills: Path | None = None,
) -> None:
    relative = Path("apply-conversation-lessons/scripts/encounter_ledger.py")
    source_script = repo / "skills" / relative
    if action == "uninstall":

        def script_options(roots: list[Path]) -> list[str]:
            paths = [source_script]
            for root in unique_roots(roots):
                if owned(root / relative.parts[0], repo / "skills" / relative.parts[0]):
                    paths.append(root / relative)
            return [item for path in paths for item in ("--script", str(path))]

        commands = [
            [
                str(source_script),
                "uninstall-codex-hooks",
                "--codex-home",
                str(codex_home),
                *script_options(
                    [
                        codex_skills,
                        codex_home / "skills",
                        claude_home.parent / ".agents/skills",
                    ]
                ),
            ],
            [
                str(source_script),
                "uninstall-claude-hooks",
                "--settings-path",
                str(claude_home / "settings.json"),
                *script_options([claude_home / "skills"]),
            ],
        ]
        if antigravity_home is not None:
            roots = [antigravity_skills] if antigravity_skills else []
            commands.append(
                [
                    str(source_script),
                    "uninstall-antigravity-hooks",
                    "--hooks-path",
                    str(antigravity_home / "hooks.json"),
                    *script_options(roots),
                ]
            )
    else:
        commands = []
        if args.codex_hooks:
            script = codex_skills / relative
            commands.append(
                [
                    str(script),
                    "install-codex-hooks",
                    "--codex-home",
                    str(codex_home),
                    "--script",
                    str(script),
                    "--mode",
                    args.codex_hooks,
                ]
            )
        if args.claude_hooks:
            script = claude_home / "skills" / relative
            commands.append(
                [
                    str(script),
                    "install-claude-hooks",
                    "--settings-path",
                    str(claude_home / "settings.json"),
                    "--script",
                    str(script),
                    "--mode",
                    args.claude_hooks,
                ]
            )
        if getattr(args, "antigravity_hooks", None) and antigravity_skills:
            script = antigravity_skills / relative
            commands.append(
                [
                    str(script),
                    "install-antigravity-hooks",
                    "--hooks-path",
                    str(antigravity_home / "hooks.json"),
                    "--script",
                    str(script),
                    "--mode",
                    args.antigravity_hooks,
                ]
            )
    if source_script.is_file():
        for command in commands:
            subprocess.run([sys.executable, *command], check=True)


def install(
    repo: Path,
    sources: list[Path],
    targets: list[Path],
    copy: bool,
    source_roots: list[Path] | None = None,
) -> None:
    # Check every target before making any change, including Claude conflicts.
    for root in targets:
        for source in sources:
            destination = root / source.name
            if present(destination) and not owned(destination, source):
                raise ValueError(
                    f"Refusing to replace unowned entry {destination}. "
                    "Inspect and move it outside discovery before installing."
                )
    revision = installed_revision(repo)
    roots = source_roots if source_roots is not None else [repo / "skills"]
    for root in targets:
        prune_retired(root, roots)
        print(f"Installing into {root} ({'copy' if copy else 'symlink'}).")
        for source in sources:
            install_skill(source, root, copy=copy, revision=revision)
    guard_source = repo / "hooks" / "pre-push"
    guard = repo / ".git" / "hooks" / "pre-push"
    if (repo / ".git").is_dir() and guard_source.is_file():
        if present(guard) and (
            guard.is_symlink() or guard.read_bytes() != guard_source.read_bytes()
        ):
            print(f"Preserved existing pre-push hook: {guard}")
        else:
            guard.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(guard_source, guard)
            guard.chmod(guard.stat().st_mode | 0o111)


def uninstall(
    source_root: Path | list[Path], sources: list[Path], targets: list[Path]
) -> None:
    roots = source_root if isinstance(source_root, list) else [source_root]
    for root in targets:
        prune_retired(root, roots)
        for source in sources:
            destination = root / source.name
            if not present(destination):
                continue
            if not owned(destination, source):
                print(f"Preserved unowned entry: {destination}")
                continue
            if destination.is_symlink():
                destination.unlink()
            elif fingerprint(destination) != fingerprint(source):
                backup = backup_copy(destination)
                print(f"Preserved changed copy in {backup}")
            else:
                shutil.rmtree(destination)
            print(f"Removed {destination}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--copy", action="store_true", help="copy instead of linking")
    parser.add_argument(
        "--user-home", type=Path, help="user root; default is the current user's home"
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        help="Codex config/hooks root; defaults to CODEX_HOME or ~/.codex",
    )
    parser.add_argument(
        "--codex-skills-dir",
        type=Path,
        help="explicit Codex discovery root; no automatic migration",
    )
    parser.add_argument(
        "--codex-hooks", nargs="?", const="audit", choices=("audit", "enforce")
    )
    parser.add_argument(
        "--claude-hooks", nargs="?", const="audit", choices=("audit", "enforce")
    )
    parser.add_argument(
        "--antigravity-home",
        type=Path,
        help="Antigravity config root; defaults to ~/.gemini/config",
    )
    parser.add_argument(
        "--antigravity-hooks", nargs="?", const="audit", choices=("audit", "enforce")
    )
    parser.add_argument(
        "--include-local",
        action="store_true",
        help="also install private skills from skills-local if present",
    )
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    user_home = (args.user_home or Path.home()).expanduser().resolve()
    # --user-home provides complete test/user isolation without changing HOME.
    configured_home = args.codex_home or (
        os.environ.get("CODEX_HOME") if args.user_home is None else None
    )
    codex_home = Path(configured_home or user_home / ".codex").expanduser().resolve()
    custom_home = codex_home != user_home / ".codex"
    claude_home = user_home / ".claude"
    antigravity_home = (
        args.antigravity_home or user_home / ".gemini" / "config"
    ).expanduser().resolve()
    # Include Antigravity when its config root exists or hooks are requested.
    include_antigravity = (
        antigravity_home.is_dir()
        or args.antigravity_hooks is not None
    )
    source_roots = [repo / "skills"]
    if getattr(args, "include_local", False) and (repo / "skills-local").is_dir():
        source_roots.append(repo / "skills-local")
    sources = [s for root in source_roots for s in skills(root)]
    try:
        if args.action == "install":
            selected, _ = codex_root(
                user_home=user_home,
                codex_home=codex_home,
                sources=sources,
                source_root=repo / "skills",
                explicit=args.codex_skills_dir,
                custom_home=custom_home,
            )
            targets = unique_roots([selected, claude_home / "skills"])
            antigravity_skills = None
            if include_antigravity:
                antigravity_skills = antigravity_home / "skills"
                targets = unique_roots(targets + [antigravity_skills])
            install(repo, sources, targets, args.copy, source_roots=source_roots)
            run_hooks(
                repo, args.action, codex_home, claude_home, selected, args,
                antigravity_home=antigravity_home if include_antigravity else None,
                antigravity_skills=antigravity_skills,
            )
            clients = ["Codex", "Claude"]
            if include_antigravity:
                clients.append("Antigravity")
            print(
                f"Done. Start a fresh {'/'.join(clients)} session to discover"
                " the installed skills."
            )
            if args.codex_hooks:
                print(
                    "In Codex, open /hooks to review and trust the installed hook definition."
                )
        else:
            selected = args.codex_skills_dir or user_home / ".agents" / "skills"
            antigravity_skills = (
                antigravity_home / "skills"
                if include_antigravity or (antigravity_home / "skills").exists()
                else None
            )
            targets = unique_roots(
                [
                    selected,
                    user_home / ".agents" / "skills",
                    codex_home / "skills",
                    claude_home / "skills",
                    *( [antigravity_skills] if antigravity_skills else [] ),
                ]
            )
            run_hooks(
                repo, args.action, codex_home, claude_home, selected, args,
                antigravity_home=antigravity_home if include_antigravity or (antigravity_home / "hooks.json").exists() else None,
                antigravity_skills=antigravity_skills,
            )
            uninstall_source_roots = [repo / "skills"]
            if (repo / "skills-local").is_dir():
                uninstall_source_roots.append(repo / "skills-local")
            uninstall_sources = [s for root in uninstall_source_roots for s in skills(root)]
            uninstall(uninstall_source_roots, uninstall_sources, targets)
            print("Done. Unowned entries and changed copies were preserved.")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Installation error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
