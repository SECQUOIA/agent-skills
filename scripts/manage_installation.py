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
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple


MARKER = ".secquoia-install.json"
INSTALLATION_ID = "secquoia-agent-skills"
HOOK_INSTALLATION_ID = "secquoia-encounter-ledger"
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


def prune_retired(root: Path, source_root: Path | list[Path]) -> None:
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


def prune_bytecode(root: Path) -> None:
    """Remove Python bytecode caches under root without following symlinks."""
    if not root.is_dir() or root.is_symlink():
        return
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in dirs:
            candidate = current_path / name
            if name == "__pycache__" and not candidate.is_symlink():
                shutil.rmtree(candidate)
            elif not candidate.is_symlink():
                kept_dirs.append(name)
        dirs[:] = kept_dirs
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                candidate = current_path / name
                if not candidate.is_symlink():
                    candidate.unlink()


def fingerprint(path: Path) -> str:
    """Compare copy contents, excluding installer bookkeeping and Python caches."""
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        relative = item.relative_to(path)
        if any(
            part in IGNORED or part.endswith((".pyc", ".pyo"))
            for part in relative.parts
        ):
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
                ignore=shutil.ignore_patterns(*IGNORED, "*.pyc", "*.pyo"),
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
        default_mode = getattr(args, "hooks", None)
        codex_mode = args.codex_hooks or default_mode
        claude_mode = args.claude_hooks or default_mode
        antigravity_mode = getattr(args, "antigravity_hooks", None) or (
            default_mode if antigravity_skills else None
        )
        commands = []
        if codex_mode:
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
                    codex_mode,
                ]
            )
        if claude_mode:
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
                    claude_mode,
                ]
            )
        if antigravity_mode and antigravity_skills and antigravity_home is not None:
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
                    antigravity_mode,
                ]
            )
    if source_script.is_file():
        for command in commands:
            subprocess.run([sys.executable, "-B", *command], check=True)


class HookConfigState(NamedTuple):
    status: str  # "configured", "absent", "disabled", "foreign", "malformed_handler", "invalid"
    mode: str | None = None
    detail: str | None = None
    owned_modes: tuple[str, ...] = ()
    foreign_modes: tuple[str, ...] = ()
    disabled_modes: tuple[str, ...] = ()
    has_malformed_handler: bool = False


def owned_hook_scripts(repo: Path, roots: list[Path]) -> set[Path]:
    relative = Path("apply-conversation-lessons/scripts/encounter_ledger.py")
    source_script = (repo / "skills" / relative).resolve()
    allowed = {source_script}
    for root in unique_roots(roots):
        if owned(root / relative.parts[0], repo / "skills" / relative.parts[0]):
            allowed.add((root / relative).resolve())
    return allowed


def _extract_hook_runner(tokens: Sequence[str]) -> Path | None:
    if not tokens:
        return None
    index = 1
    while index < len(tokens) and tokens[index] == "-B":
        index += 1
    if (
        index + 1 >= len(tokens)
        or tokens[index].startswith("-")
        or tokens[index + 1] != "hook"
    ):
        return None
    return Path(tokens[index])


def _classify_handler_command(
    command: str, allowed_scripts: set[Path] | None = None
) -> tuple[str, str | None]:
    if HOOK_INSTALLATION_ID not in command:
        return ("other", None)
    try:
        tokens = shlex.split(command)
    except ValueError:
        return ("malformed", None)
    mode = "configured"
    for index, token in enumerate(tokens):
        if token == "--mode" and index + 1 < len(tokens):
            mode = tokens[index + 1]
            break
        if token.startswith("--mode="):
            mode = token.split("=", 1)[1]
            break
    if allowed_scripts is not None:
        runner = _extract_hook_runner(tokens)
        if runner is None:
            return ("foreign", mode)
        try:
            is_valid_runner = runner.is_file() and runner.resolve() in allowed_scripts
        except OSError:
            is_valid_runner = False
        if not is_valid_runner:
            return ("foreign", mode)
    return ("owned", mode)


def inspect_hook_config(
    path: Path,
    *,
    antigravity: bool = False,
    allowed_scripts: set[Path] | None = None,
) -> HookConfigState:
    try:
        exists = path.exists() or path.is_symlink()
    except OSError as exc:
        return HookConfigState("invalid", detail=f"unreadable ({type(exc).__name__})")
    if not exists:
        return HookConfigState("absent")
    if not path.is_file():
        return HookConfigState("invalid", detail="not a regular file")
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return HookConfigState("invalid", detail="invalid UTF-8 encoding")
    except OSError as exc:
        return HookConfigState("invalid", detail=f"unreadable ({type(exc).__name__})")
    try:
        document = json.loads(raw)
    except ValueError:
        return HookConfigState("invalid", detail="invalid JSON")
    if not isinstance(document, dict):
        return HookConfigState("invalid", detail="top-level JSON value must be an object")

    owned_modes: set[str] = set()
    disabled_modes: set[str] = set()
    foreign_modes: set[str] = set()
    malformed_cmd = False

    if antigravity:
        for spec in document.values():
            if not isinstance(spec, dict):
                continue
            is_disabled = spec.get("enabled") is False
            for items in spec.values():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    handlers = item.get("hooks") if isinstance(item.get("hooks"), list) else [item]
                    for handler in handlers:
                        if isinstance(handler, dict) and isinstance(handler.get("command"), str):
                            kind, mode = _classify_handler_command(
                                handler["command"], allowed_scripts
                            )
                            if kind == "owned" and mode:
                                if is_disabled:
                                    disabled_modes.add(mode)
                                else:
                                    owned_modes.add(mode)
                            elif kind == "foreign" and mode:
                                if is_disabled:
                                    disabled_modes.add(mode)
                                else:
                                    foreign_modes.add(mode)
                            elif kind == "malformed":
                                malformed_cmd = True
    else:
        if "hooks" in document and not isinstance(document["hooks"], dict):
            return HookConfigState("invalid", detail="'hooks' field must be a JSON object")
        hooks = document.get("hooks")
        if isinstance(hooks, dict):
            for groups in hooks.values():
                if not isinstance(groups, list):
                    continue
                for group in groups:
                    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                        continue
                    for handler in group["hooks"]:
                        if isinstance(handler, dict) and isinstance(handler.get("command"), str):
                            kind, mode = _classify_handler_command(
                                handler["command"], allowed_scripts
                            )
                            if kind == "owned" and mode:
                                owned_modes.add(mode)
                            elif kind == "foreign" and mode:
                                foreign_modes.add(mode)
                            elif kind == "malformed":
                                malformed_cmd = True

    owned_tuple = tuple(sorted(owned_modes))
    foreign_tuple = tuple(sorted(foreign_modes))
    disabled_tuple = tuple(sorted(disabled_modes))

    if owned_tuple:
        details: list[str] = []
        if foreign_tuple:
            details.append(
                f"also has other-checkout/missing-runner handler(s): {'/'.join(foreign_tuple)}"
            )
        if malformed_cmd:
            details.append("also has malformed SECQUOIA hook command")
        return HookConfigState(
            "configured",
            mode="/".join(owned_tuple),
            detail="; ".join(details) if details else None,
            owned_modes=owned_tuple,
            foreign_modes=foreign_tuple,
            disabled_modes=disabled_tuple,
            has_malformed_handler=malformed_cmd,
        )
    if foreign_tuple:
        detail = "other checkout or missing runner"
        if malformed_cmd:
            detail += "; also has malformed SECQUOIA hook command"
        return HookConfigState(
            "foreign",
            mode="/".join(foreign_tuple),
            detail=detail,
            foreign_modes=foreign_tuple,
            disabled_modes=disabled_tuple,
            has_malformed_handler=malformed_cmd,
        )
    if malformed_cmd:
        return HookConfigState(
            "malformed_handler",
            detail="malformed SECQUOIA hook command",
            disabled_modes=disabled_tuple,
            has_malformed_handler=True,
        )
    if disabled_tuple:
        return HookConfigState(
            "disabled",
            mode="/".join(disabled_tuple),
            detail="enabled: false",
            disabled_modes=disabled_tuple,
        )
    return HookConfigState("absent")


def installed_hook_mode(
    path: Path,
    *,
    antigravity: bool = False,
    allowed_scripts: set[Path] | None = None,
) -> str | None:
    state = inspect_hook_config(
        path, antigravity=antigravity, allowed_scripts=allowed_scripts
    )
    return state.mode if state.status == "configured" else None


def build_base_install_args(
    args: argparse.Namespace,
    *,
    codex_home: Path,
    custom_home: bool,
) -> list[str]:
    preserved: list[str] = []
    if getattr(args, "copy", False):
        preserved.append("--copy")
    if getattr(args, "user_home", None) is not None:
        preserved.append(f"--user-home={args.user_home}")
    if getattr(args, "codex_home", None) is not None:
        preserved.append(f"--codex-home={args.codex_home}")
    elif custom_home and getattr(args, "user_home", None) is None:
        preserved.append(f"--codex-home={codex_home}")
    if getattr(args, "codex_skills_dir", None) is not None:
        preserved.append(f"--codex-skills-dir={args.codex_skills_dir}")
    if getattr(args, "antigravity_home", None) is not None:
        preserved.append(f"--antigravity-home={args.antigravity_home}")
    if getattr(args, "include_local", False):
        preserved.append("--include-local")
    return preserved


def _quote_flag(arg: str) -> str:
    if "=" in arg and arg.startswith("--"):
        flag, value = arg.split("=", 1)
        return f"{flag}={shlex.quote(value)}"
    return shlex.quote(arg)


def format_install_command(base_args: Sequence[str], hook_args: Sequence[str]) -> str:
    parts = [
        "./install.sh",
        *(_quote_flag(a) for a in base_args),
        *(_quote_flag(a) for a in hook_args),
    ]
    return " ".join(parts)


def _client_clean_modes(state: HookConfigState) -> set[str]:
    return {
        m
        for m in (*state.owned_modes, *state.foreign_modes, *state.disabled_modes)
        if m in {"audit", "enforce"}
    }


def _is_healthy_owned(state: HookConfigState) -> bool:
    return (
        state.status == "configured"
        and len(state.owned_modes) == 1
        and state.owned_modes[0] in {"audit", "enforce"}
        and not state.foreign_modes
        and not state.has_malformed_handler
    )


def _format_repair_target(name: str, path: Path, state: HookConfigState) -> str:
    if state.status == "absent":
        return f"{name} ({path})"
    if state.status == "foreign" and state.mode:
        return f"{name} ({path}: {state.detail}, mode={state.mode})"
    if state.detail:
        return f"{name} ({path}: {state.detail})"
    return f"{name} ({path}: mode={state.mode})"


def report_hook_parity(
    codex_home: Path,
    claude_home: Path,
    antigravity_home: Path | None,
    *,
    base_install_args: Sequence[str] = (),
    allowed_scripts_by_client: dict[str, set[Path] | None] | None = None,
) -> None:
    allowed_map = allowed_scripts_by_client or {}
    targets: list[tuple[str, str, Path, bool]] = [
        ("Codex", "--codex-hooks", codex_home / "hooks.json", False),
        ("Claude", "--claude-hooks", claude_home / "settings.json", False),
    ]
    if antigravity_home is not None:
        targets.append(
            ("Antigravity", "--antigravity-hooks", antigravity_home / "hooks.json", True)
        )
    inspected = [
        (
            name,
            hook_flag,
            path,
            inspect_hook_config(
                path,
                antigravity=is_agy,
                allowed_scripts=allowed_map.get(name),
            ),
        )
        for name, hook_flag, path, is_agy in targets
    ]
    invalid = [
        (name, hook_flag, path, state)
        for name, hook_flag, path, state in inspected
        if state.status == "invalid"
    ]
    for name, _, path, state in invalid:
        print(
            f"Hook parity warning: invalid hook configuration for {name}"
            f" ({path}: {state.detail}). Repair or back up that file before installing hooks."
        )

    valid_clients = [
        (name, hook_flag, path, state)
        for name, hook_flag, path, state in inspected
        if state.status != "invalid"
    ]
    for name, _, path, state in valid_clients:
        if state.has_malformed_handler:
            print(
                f"Hook parity warning: malformed SECQUOIA hook command in {name} ({path})."
            )
        if state.owned_modes and state.foreign_modes:
            print(
                f"Hook parity warning: {name} ({path}) mixes this checkout's hooks"
                f" ({'/'.join(state.owned_modes)}) with another checkout or missing runner"
                f" ({'/'.join(state.foreign_modes)})."
            )

    has_active_or_broken = any(
        bool(state.owned_modes or state.foreign_modes or state.has_malformed_handler)
        for _, _, _, state in valid_clients
    )
    if not has_active_or_broken:
        return

    global_active_modes = {
        m
        for _, _, _, state in valid_clients
        for m in (*state.owned_modes, *state.foreign_modes)
        if m in {"audit", "enforce"}
    }
    default_new_mode = "enforce" if global_active_modes == {"enforce"} else "audit"

    def preserved_mode(state: HookConfigState) -> str:
        modes = _client_clean_modes(state)
        if "enforce" in modes:
            return "enforce"
        if "audit" in modes:
            return "audit"
        return default_new_mode

    needs_repair = [
        (name, hook_flag, path, state)
        for name, hook_flag, path, state in valid_clients
        if not _is_healthy_owned(state)
    ]
    healthy = [
        (name, hook_flag, path, state)
        for name, hook_flag, path, state in valid_clients
        if _is_healthy_owned(state)
    ]

    if not needs_repair:
        healthy_modes = {state.owned_modes[0] for _, _, _, state in healthy}
        configured_text = ", ".join(
            f"{name} ({state.mode})" for name, _, _, state in healthy
        )
        if not invalid:
            if len(healthy_modes) <= 1:
                return
            audit_cmd = format_install_command(base_install_args, ["--hooks=audit"])
            enforce_cmd = format_install_command(base_install_args, ["--hooks=enforce"])
            print(
                f"Hook parity note: SECQUOIA encounter hooks use mixed modes across clients: {configured_text}."
                f" Run {audit_cmd} or {enforce_cmd} if you want one mode across all active clients."
            )
            return
        invalid_names = ", ".join(name for name, _, _, _ in invalid)
        hook_args = (
            [f"--hooks={next(iter(healthy_modes))}"]
            if len(healthy_modes) == 1
            else [f"{hook_flag}={default_new_mode}" for _, hook_flag, _, _ in invalid]
        )
        cmd = format_install_command(base_install_args, hook_args)
        print(
            f"Hook parity note: SECQUOIA encounter hooks are configured for {configured_text};"
            f" after fixing the invalid configuration for {invalid_names}, run {cmd}."
        )
        return

    all_target_modes = {preserved_mode(state) for _, _, _, state in valid_clients}
    can_use_unified_flag = (
        not invalid
        and len(all_target_modes) == 1
        and all(len(_client_clean_modes(state)) <= 1 for _, _, _, state in valid_clients)
    )
    repair_text = ", ".join(
        _format_repair_target(name, path, state) for name, _, path, state in needs_repair
    )
    if can_use_unified_flag:
        uniform_mode = next(iter(all_target_modes))
        cmd = format_install_command(base_install_args, [f"--hooks={uniform_mode}"])
        if healthy:
            healthy_text = ", ".join(
                f"{name} ({state.mode})" for name, _, _, state in healthy
            )
            print(
                f"Hook parity note: SECQUOIA encounter hooks are configured for {healthy_text}"
                f" but missing or inactive for {repair_text}. Run {cmd} to align all active clients."
            )
        else:
            print(
                f"Hook parity note: SECQUOIA encounter hooks need refresh for {repair_text}."
                f" Run {cmd} to align all active clients."
            )
        return

    per_client_flags = [
        f"{hook_flag}={preserved_mode(state)}" for _, hook_flag, _, state in needs_repair
    ]
    preserve_cmd = format_install_command(base_install_args, per_client_flags)
    active_descriptions = []
    for name, _, _, state in valid_clients:
        if state.status == "configured":
            label = f"{name} ({state.mode})"
            if state.foreign_modes:
                label += f" + foreign ({'/'.join(state.foreign_modes)})"
            active_descriptions.append(label)
        elif state.status == "foreign":
            active_descriptions.append(f"{name} (foreign {state.mode})")
    active_text = ", ".join(active_descriptions) if active_descriptions else "partial/broken handlers"
    print(
        f"Hook parity note: SECQUOIA encounter hooks have active state [{active_text}]"
        f" and need setup or refresh for {repair_text}. Run {preserve_cmd} to configure"
        f" the remaining client(s) without changing existing modes"
        f" (or pass --hooks=audit / --hooks=enforce once all hook files are valid to set one mode across all active clients)."
    )


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
    for source_root in roots:
        prune_bytecode(source_root)
    for root in targets:
        prune_retired(root, roots)
        print(f"Installing into {root} ({'copy' if copy else 'symlink'}).")
        for source in sources:
            install_skill(source, root, copy=copy, revision=revision)
            if copy:
                prune_bytecode(root / source.name)
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
        "--hooks",
        nargs="?",
        const="audit",
        choices=("audit", "enforce"),
        help="install encounter hooks across all active clients (audit or enforce)",
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
    # Include Antigravity when explicit, when ~/.gemini exists, or when config root exists or hooks are requested.
    include_antigravity = (
        args.antigravity_home is not None
        or (user_home / ".gemini").is_dir()
        or antigravity_home.is_dir()
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
            if args.codex_hooks or args.hooks:
                print(
                    "In Codex, open /hooks to review and trust the installed hook definition."
                )
            source_script = repo / "skills/apply-conversation-lessons/scripts/encounter_ledger.py"
            allowed_scripts_by_client: dict[str, set[Path] | None] | None = None
            if source_script.is_file():
                allowed_scripts_by_client = {
                    "Codex": owned_hook_scripts(
                        repo,
                        [selected, codex_home / "skills", user_home / ".agents/skills"],
                    ),
                    "Claude": owned_hook_scripts(repo, [claude_home / "skills"]),
                }
                if include_antigravity:
                    allowed_scripts_by_client["Antigravity"] = owned_hook_scripts(
                        repo, [antigravity_skills] if antigravity_skills else []
                    )
            report_hook_parity(
                codex_home,
                claude_home,
                antigravity_home if include_antigravity else None,
                base_install_args=build_base_install_args(
                    args, codex_home=codex_home, custom_home=custom_home
                ),
                allowed_scripts_by_client=allowed_scripts_by_client,
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
