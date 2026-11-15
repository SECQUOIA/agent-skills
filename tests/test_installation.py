from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="secquoia-install-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo with spaces"
        self.home = self.base / "isolated user"
        self.repo.mkdir()
        for name in ("install.sh", "uninstall.sh"):
            shutil.copy2(REPO / name, self.repo / name)
        shutil.copytree(
            REPO / "scripts",
            self.repo / "scripts",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        self.source = self.repo / "skills" / "sample-skill"
        self.source.mkdir(parents=True)
        (self.source / "SKILL.md").write_text(
            "---\nname: sample-skill\ndescription: sample\n---\nSkill instructions.\n"
        )
        self.ledger_source = self.repo / "skills" / "apply-conversation-lessons"
        (self.ledger_source / "scripts").mkdir(parents=True)
        (self.ledger_source / "SKILL.md").write_text(
            "---\nname: apply-conversation-lessons\ndescription: sample\n---\n"
        )
        shutil.copy2(
            REPO / "skills/apply-conversation-lessons/scripts/encounter_ledger.py",
            self.ledger_source / "scripts/encounter_ledger.py",
        )

    @property
    def modern(self):
        return self.home / ".agents/skills"

    @property
    def legacy(self):
        return self.home / ".codex/skills"

    @property
    def claude(self):
        return self.home / ".claude/skills"

    @property
    def antigravity(self):
        return self.home / ".gemini/config/skills"

    def run_script(self, action="install", *arguments, expected=0):
        result = subprocess.run(
            [
                "bash",
                str(self.repo / f"{action}.sh"),
                "--user-home",
                str(self.home),
                *map(str, arguments),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def link(self, root, source=None):
        source = source or self.source
        root.mkdir(parents=True, exist_ok=True)
        (root / source.name).symlink_to(source, target_is_directory=True)

    def hooks(self, path):
        document = json.loads(path.read_text())
        return [
            handler
            for groups in document.get("hooks", {}).values()
            for group in groups
            for handler in group["hooks"]
        ]

    def test_fresh_symlink_install_is_repeatable_and_discovered_only_once(self):
        self.run_script()
        self.run_script()
        for root in (self.modern, self.claude):
            self.assertEqual((root / "sample-skill").resolve(), self.source)
            self.assertTrue((root / "apply-conversation-lessons").is_symlink())
        self.assertFalse(self.legacy.exists())
        self.assertEqual(list(self.home.rglob(".secquoia-skill-backups")), [])
        self.run_script("uninstall")
        self.run_script("uninstall")
        self.assertFalse((self.modern / "sample-skill").exists())
        self.assertTrue((self.source / "SKILL.md").is_file())

    def test_partial_existing_legacy_install_stays_in_legacy_root(self):
        self.link(self.legacy)
        self.run_script("install", "--codex-hooks")
        self.assertTrue((self.legacy / "apply-conversation-lessons").is_symlink())
        self.assertFalse(self.modern.exists())
        for handler in self.hooks(self.home / ".codex/hooks.json"):
            self.assertIn(str(self.legacy), handler["command"])

    def test_copy_repeat_install_preserves_revision_and_does_not_create_backups(self):
        self.run_script("install", "--copy")
        self.run_script("install", "--copy")
        for root in (self.modern, self.claude):
            installed = root / "sample-skill"
            self.assertFalse(installed.is_symlink())
            marker = json.loads((installed / ".secquoia-install.json").read_text())
            self.assertEqual(marker["source"], str(self.source))
            self.assertEqual(
                (
                    root / "apply-conversation-lessons/scripts/.installed-revision"
                ).read_text(),
                "unknown\n",
            )
        self.assertEqual(list(self.home.rglob(".secquoia-skill-backups")), [])
        self.run_script("uninstall")
        self.assertFalse((self.modern / "sample-skill").exists())

    def test_copy_update_and_uninstall_back_up_user_changes_outside_discovery(self):
        self.run_script("install", "--copy")
        installed = self.modern / "sample-skill/SKILL.md"
        installed.write_text("local user edits")
        self.run_script("install", "--copy")
        self.assertEqual(installed.read_text(), (self.source / "SKILL.md").read_text())
        backups = list(
            (self.modern.parent / ".secquoia-skill-backups").rglob("SKILL.md")
        )
        self.assertEqual([path.read_text() for path in backups], ["local user edits"])
        installed.write_text("other local edits")
        self.run_script("uninstall")
        backups = list(
            (self.modern.parent / ".secquoia-skill-backups").rglob("SKILL.md")
        )
        self.assertEqual(
            {path.read_text() for path in backups},
            {"local user edits", "other local edits"},
        )

    def test_copy_to_symlink_conversion_preserves_previous_copy(self):
        self.run_script("install", "--copy")
        self.run_script()
        self.assertTrue((self.modern / "sample-skill").is_symlink())
        self.assertTrue(
            list((self.modern.parent / ".secquoia-skill-backups").rglob("SKILL.md"))
        )

    def test_foreign_claude_entry_fails_preflight_before_installing_codex(self):
        destination = self.claude / "sample-skill"
        destination.mkdir(parents=True)
        (destination / "SKILL.md").write_text("foreign instructions")
        result = self.run_script(expected=1)
        self.assertIn("Refusing to replace unowned", result.stderr)
        self.assertFalse(self.modern.exists())
        self.assertEqual((destination / "SKILL.md").read_text(), "foreign instructions")

    def test_unmarked_legacy_copy_does_not_cause_a_duplicate_modern_install(self):
        shutil.copytree(self.source, self.legacy / "sample-skill")
        self.run_script(expected=1)
        self.assertFalse(self.modern.exists())
        self.run_script("uninstall")
        self.assertTrue((self.legacy / "sample-skill/SKILL.md").is_file())

    def test_foreign_and_broken_symlinks_are_never_replaced_or_removed(self):
        self.modern.mkdir(parents=True)
        foreign = self.base / "foreign skill"
        foreign.mkdir()
        (foreign / "SKILL.md").write_text("foreign")
        destination = self.modern / "sample-skill"
        destination.symlink_to(foreign, target_is_directory=True)
        self.run_script(expected=1)
        self.run_script("uninstall")
        self.assertEqual(destination.resolve(), foreign)
        shutil.rmtree(foreign)
        self.run_script(expected=1)
        self.run_script("uninstall")
        self.assertTrue(destination.is_symlink())

    def test_dual_discovery_is_rejected_without_deleting_either_install(self):
        self.link(self.modern)
        self.link(self.legacy)
        result = self.run_script(expected=1)
        self.assertIn("another Codex discovery root", result.stderr)
        self.assertTrue((self.modern / "sample-skill").is_symlink())
        self.assertTrue((self.legacy / "sample-skill").is_symlink())
        self.assertFalse(self.claude.exists())
        self.run_script("uninstall")
        self.assertFalse((self.modern / "sample-skill").is_symlink())
        self.assertFalse((self.legacy / "sample-skill").is_symlink())

    def test_custom_codex_home_keeps_skills_and_hooks_together(self):
        configured = self.base / "custom codex"
        self.run_script("install", "--codex-home", configured, "--codex-hooks=enforce")
        self.assertTrue((configured / "skills/sample-skill").is_symlink())
        self.assertFalse(self.modern.exists())
        for handler in self.hooks(configured / "hooks.json"):
            self.assertIn(str(configured / "skills"), handler["command"])
            self.assertIn("--mode enforce", handler["command"])
        self.run_script("uninstall", "--codex-home", configured)
        self.assertEqual(self.hooks(configured / "hooks.json"), [])

    def test_explicit_discovery_root_and_hooks_survive_spaces_and_safe_uninstall(self):
        target = self.base / "custom discovery/skills"
        settings = self.home / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "model": "unchanged",
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {"type": "command", "command": "echo user-hook"}
                                ],
                            }
                        ],
                    },
                }
            )
        )
        self.run_script(
            "install",
            "--codex-skills-dir",
            target,
            "--copy",
            "--codex-hooks",
            "--claude-hooks",
        )
        self.run_script(
            "install",
            "--codex-skills-dir",
            target,
            "--copy",
            "--codex-hooks",
            "--claude-hooks",
        )
        self.assertFalse(self.modern.exists())
        self.assertFalse(self.legacy.exists())
        for handler in self.hooks(self.home / ".codex/hooks.json"):
            self.assertIn(str(target), handler["command"])
        self.run_script("uninstall", "--codex-skills-dir", target)
        self.assertFalse((target / "sample-skill").exists())
        document = json.loads(settings.read_text())
        self.assertEqual(document["model"], "unchanged")
        self.assertEqual(
            [row["command"] for row in self.hooks(settings)], ["echo user-hook"]
        )

    def test_explicit_root_cannot_duplicate_existing_discovery(self):
        self.link(self.legacy)
        custom = self.base / "new discovery"
        self.run_script("install", "--codex-skills-dir", custom, expected=1)
        self.assertFalse(custom.exists())
        self.assertTrue((self.legacy / "sample-skill").is_symlink())

    def test_uninstall_preserves_hooks_owned_by_another_checkout(self):
        hook = {
            "type": "command",
            "command": "/usr/bin/python3 /another/checkout/encounter_ledger.py hook --agent codex --mode audit --installation-id secquoia-encounter-ledger",
        }
        hooks_path = self.home / ".codex/hooks.json"
        hooks_path.parent.mkdir(parents=True)
        hooks_path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [hook]}]}}))
        self.run_script("uninstall")
        self.assertEqual(self.hooks(hooks_path), [hook])

    def test_install_backs_up_retired_owned_copies_with_local_edits(self):
        self.run_script("install", "--copy")
        (self.modern / "sample-skill/SKILL.md").write_text("retired local edits")
        original = (self.source / "SKILL.md").read_text()
        shutil.rmtree(self.source)
        self.run_script("install", "--copy")
        self.run_script("install", "--copy")
        for root, expected in (
            (self.modern, "retired local edits"),
            (self.claude, original),
        ):
            self.assertFalse((root / "sample-skill").exists())
            backups = list(
                (root.parent / ".secquoia-skill-backups").rglob("sample-skill/SKILL.md")
            )
            self.assertEqual([path.read_text() for path in backups], [expected])
            self.assertTrue((root / "apply-conversation-lessons/SKILL.md").exists())

    def test_uninstall_preserves_retired_owned_copies_outside_discovery(self):
        self.run_script("install", "--copy")
        original = (self.source / "SKILL.md").read_text()
        shutil.rmtree(self.source)
        self.run_script("uninstall")
        self.run_script("uninstall")
        for root in (self.modern, self.claude):
            self.assertFalse((root / "sample-skill").exists())
            backups = list(
                (root.parent / ".secquoia-skill-backups").rglob("sample-skill/SKILL.md")
            )
            self.assertEqual([path.read_text() for path in backups], [original])

    def test_retired_owned_legacy_link_selects_legacy_root_then_is_removed(self):
        self.link(self.legacy)
        shutil.rmtree(self.source)
        self.run_script()
        self.assertFalse((self.legacy / "sample-skill").is_symlink())
        self.assertTrue((self.legacy / "apply-conversation-lessons").is_symlink())
        self.assertFalse(self.modern.exists())
        # Uninstall also recognizes a subsequently encountered retired link.
        self.link(self.legacy)
        self.run_script("uninstall")
        self.assertFalse((self.legacy / "sample-skill").is_symlink())

    def test_retired_foreign_unmarked_and_other_clone_entries_are_preserved(self):
        shutil.copytree(self.source, self.modern / "sample-skill")
        shutil.copytree(self.source, self.claude / "sample-skill")
        (self.claude / "sample-skill/.secquoia-install.json").write_text(
            json.dumps(
                {
                    "installation": "secquoia-agent-skills",
                    "source": str(self.base / "different-clone/skills/sample-skill"),
                }
            )
        )
        foreign_link = self.modern / "different-clone-link"
        foreign_link.symlink_to(
            self.base / "different-clone/skills/different-clone-link"
        )
        alias_link = self.modern / "wrong-name"
        alias_link.symlink_to(self.source)
        expected = (self.source / "SKILL.md").read_text()
        marker = (self.claude / "sample-skill/.secquoia-install.json").read_text()
        shutil.rmtree(self.source)
        self.run_script("install", "--copy")
        self.run_script("uninstall")
        self.assertEqual((self.modern / "sample-skill/SKILL.md").read_text(), expected)
        self.assertEqual((self.claude / "sample-skill/SKILL.md").read_text(), expected)
        self.assertEqual(
            (self.claude / "sample-skill/.secquoia-install.json").read_text(), marker
        )
        self.assertTrue(foreign_link.is_symlink())
        self.assertTrue(alias_link.is_symlink())
        self.assertEqual(list(self.home.rglob(".secquoia-skill-backups")), [])

    def test_current_source_conflict_prevents_any_retired_entry_pruning(self):
        self.run_script("install", "--copy")
        shutil.rmtree(self.source)
        foreign = self.claude / "apply-conversation-lessons"
        shutil.rmtree(foreign)
        foreign.mkdir()
        (foreign / "SKILL.md").write_text("foreign instructions")
        self.run_script("install", "--copy", expected=1)
        for root in (self.modern, self.claude):
            self.assertTrue((root / "sample-skill/SKILL.md").is_file())
        self.assertEqual(list(self.home.rglob(".secquoia-skill-backups")), [])
        self.assertEqual((foreign / "SKILL.md").read_text(), "foreign instructions")

    def test_antigravity_discovery_when_gemini_config_exists(self):
        # Auto-detected when ~/.gemini exists (even before config/ is created)
        (self.home / ".gemini").mkdir(parents=True)
        self.run_script("install")
        for root in (self.modern, self.claude, self.antigravity):
            self.assertEqual((root / "sample-skill").resolve(), self.source)
            self.assertTrue((root / "apply-conversation-lessons").is_symlink())
        self.run_script("uninstall")
        self.assertFalse((self.antigravity / "sample-skill").exists())

    def test_antigravity_home_custom_directory_override(self):
        custom_gemini = self.home / "custom_gemini"
        custom_skills = custom_gemini / "skills"
        self.run_script("install", f"--antigravity-home={custom_gemini}", "--antigravity-hooks=audit")
        self.assertTrue((custom_skills / "sample-skill").is_symlink())
        hooks_file = custom_gemini / "hooks.json"
        self.assertTrue(hooks_file.is_file())
        data = json.loads(hooks_file.read_text())
        self.assertIn("secquoia-hooks", data)
        self.run_script("uninstall", f"--antigravity-home={custom_gemini}")
        self.assertFalse((custom_skills / "sample-skill").exists())
        updated_data = json.loads(hooks_file.read_text())
        self.assertNotIn("secquoia-hooks", updated_data)

    def test_antigravity_hooks_installation_and_uninstallation(self):
        self.run_script("install", "--antigravity-hooks=audit")
        hooks_file = self.home / ".gemini/config/hooks.json"
        self.assertTrue(hooks_file.is_file())
        data = json.loads(hooks_file.read_text())
        self.assertIn("secquoia-hooks", data)
        self.assertNotIn("hooks", data)
        secquoia = data["secquoia-hooks"]
        self.assertIn("PreToolUse", secquoia)
        self.assertEqual(secquoia["PreToolUse"][0]["matcher"], "run_command")
        self.assertIn("PostToolUse", secquoia)
        self.assertIn("SessionStart", secquoia)
        self.assertIn("Stop", secquoia)
        self.run_script("uninstall")
        updated_data = json.loads(hooks_file.read_text())
        self.assertNotIn("secquoia-hooks", updated_data)
        self.assertNotIn("hooks", updated_data)

    def test_include_local_installs_private_skills(self):
        private = self.repo / "skills-local/private-skill"
        private.mkdir(parents=True)
        (private / "SKILL.md").write_text("---\nname: private-skill\ndescription: private\n---\n")
        self.run_script("install", "--include-local")
        for root in (self.modern, self.claude):
            self.assertTrue((root / "private-skill").is_symlink())
            self.assertEqual((root / "private-skill").resolve(), private)
        self.run_script("uninstall")
        for root in (self.modern, self.claude):
            self.assertFalse((root / "private-skill").exists())

    def test_unified_hooks_flag_and_hook_parity_notice(self):
        # 1. Partial hook install followed by Antigravity discovery warns without mutating hooks.json
        self.run_script("install", "--codex-hooks", "--claude-hooks")
        (self.home / ".gemini").mkdir(parents=True)
        drift = self.run_script("install")
        self.assertIn("Hook parity note:", drift.stdout)
        self.assertIn("Antigravity", drift.stdout)
        self.assertIn("--hooks=audit", drift.stdout)
        self.assertFalse((self.home / ".gemini/config/hooks.json").exists())

        # 2. --hooks aligns all active clients (Codex, Claude, Antigravity) and clears drift warning
        aligned = self.run_script("install", "--hooks")
        self.assertNotIn("Hook parity note:", aligned.stdout)
        self.assertTrue((self.home / ".gemini/config/hooks.json").is_file())
        agy_doc = json.loads((self.home / ".gemini/config/hooks.json").read_text())
        self.assertIn("--mode audit", agy_doc["secquoia-hooks"]["PreToolUse"][0]["hooks"][0]["command"])

        # 3. Client-specific hook flag overrides --hooks and reports mixed-mode parity note
        mixed = self.run_script("install", "--hooks=audit", "--claude-hooks=enforce")
        self.assertIn("mixed modes across clients", mixed.stdout)
        claude_cmds = [h["command"] for h in self.hooks(self.home / ".claude/settings.json")]
        self.assertTrue(all("--mode enforce" in c for c in claude_cmds))

    def test_hook_parity_preserves_custom_roots_copy_and_prevents_mode_downgrade(self):
        private = self.repo / "skills-local/private-skill"
        private.mkdir(parents=True)
        (private / "SKILL.md").write_text("---\nname: private-skill\ndescription: private\n---\n")

        custom_codex = self.base / "custom codex"
        custom_codex_skills = custom_codex / "custom skills"
        custom_agy = self.base / "custom gemini config"

        # 1. Custom roots + --copy + --include-local + enforce on Codex only
        self.run_script(
            "install",
            "--copy",
            "--include-local",
            f"--codex-home={custom_codex}",
            f"--codex-skills-dir={custom_codex_skills}",
            f"--antigravity-home={custom_agy}",
            "--codex-hooks=enforce",
        )
        drift = self.run_script(
            "install",
            "--copy",
            "--include-local",
            f"--codex-home={custom_codex}",
            f"--codex-skills-dir={custom_codex_skills}",
            f"--antigravity-home={custom_agy}",
        )
        match = re.search(r"Run (\./install\.sh .+?) to align all active clients\.", drift.stdout)
        self.assertIsNotNone(match, drift.stdout)
        tokens = shlex.split(match.group(1))
        self.assertEqual(tokens[0], "./install.sh")
        self.assertIn("--copy", tokens)
        self.assertIn("--include-local", tokens)
        self.assertIn(f"--user-home={self.home}", tokens)
        self.assertIn(f"--codex-home={custom_codex}", tokens)
        self.assertIn(f"--codex-skills-dir={custom_codex_skills}", tokens)
        self.assertIn(f"--antigravity-home={custom_agy}", tokens)
        self.assertIn("--hooks=enforce", tokens)

        # Executing the exact suggested command aligns custom targets without touching default roots
        repair = subprocess.run(
            ["bash", str(self.repo / "install.sh"), *tokens[1:]],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(repair.returncode, 0, repair.stdout + repair.stderr)
        self.assertNotIn("Hook parity note:", repair.stdout)
        self.assertFalse((self.home / ".codex/hooks.json").exists())
        self.assertFalse((self.home / ".gemini/config/hooks.json").exists())
        agy_doc = json.loads((custom_agy / "hooks.json").read_text())
        self.assertIn(
            "--mode enforce",
            agy_doc["secquoia-hooks"]["PreToolUse"][0]["hooks"][0]["command"],
        )
        self.assertFalse((custom_agy / "skills/sample-skill").is_symlink())
        self.assertTrue((custom_agy / "skills/private-skill").is_dir())

        # 2. Mixed modes (Codex=enforce, Claude=audit) + missing Antigravity preserves Codex=enforce
        mixed_home = self.base / "mixed home"
        (mixed_home / ".gemini").mkdir(parents=True)
        for args in (
            ("--codex-hooks=enforce", "--claude-hooks=audit"),
            (),
        ):
            res = subprocess.run(
                ["bash", str(self.repo / "install.sh"), "--user-home", str(mixed_home), *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("--antigravity-hooks=audit", res.stdout)
        self.assertIn("without changing existing modes", res.stdout)
        preserve_match = re.search(
            r"Run (\./install\.sh .+?) to configure the remaining client\(s\)",
            res.stdout,
        )
        self.assertIsNotNone(preserve_match, res.stdout)
        preserve_tokens = shlex.split(preserve_match.group(1))
        preserve_run = subprocess.run(
            ["bash", str(self.repo / "install.sh"), *preserve_tokens[1:]],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(preserve_run.returncode, 0, preserve_run.stdout + preserve_run.stderr)
        codex_cmds = [h["command"] for h in self.hooks(mixed_home / ".codex/hooks.json")]
        self.assertTrue(all("--mode enforce" in c for c in codex_cmds))
        agy_mixed_doc = json.loads((mixed_home / ".gemini/config/hooks.json").read_text())
        self.assertIn(
            "--mode audit",
            agy_mixed_doc["secquoia-hooks"]["PreToolUse"][0]["hooks"][0]["command"],
        )

    def test_hook_parity_reports_malformed_disabled_and_foreign_checkout_configs(self):
        # 1. Malformed config when no client is configured still emits warning without leaking contents
        agy_hooks = self.home / ".gemini/config/hooks.json"
        agy_hooks.parent.mkdir(parents=True)
        agy_hooks.write_text("{broken-json: SECRET_TOKEN_123")
        malformed_only = self.run_script("install")
        self.assertIn("Hook parity warning: invalid hook configuration for Antigravity", malformed_only.stdout)
        self.assertIn("invalid JSON", malformed_only.stdout)
        self.assertNotIn("SECRET_TOKEN_123", malformed_only.stdout)

        # 2. Valid Codex + malformed Antigravity + absent Claude recommends --claude-hooks=audit safely
        with_codex = self.run_script("install", "--codex-hooks=audit")
        self.assertIn("Hook parity warning: invalid hook configuration for Antigravity", with_codex.stdout)
        self.assertIn("--claude-hooks=audit", with_codex.stdout)
        self.assertNotIn("Run ./install.sh --hooks=audit", with_codex.stdout)

        # 3. Disabled Antigravity hook ("enabled": false) is reported as disabled rather than configured
        self.run_script("install", "--claude-hooks=audit")
        agy_hooks.write_text(
            json.dumps(
                {
                    "secquoia-hooks": {
                        "enabled": False,
                        "Stop": [
                            {
                                "type": "command",
                                "command": (
                                    f"python3 '{self.antigravity / 'apply-conversation-lessons/scripts/encounter_ledger.py'}'"
                                    " hook --agent antigravity --mode audit --installation-id secquoia-encounter-ledger --event Stop"
                                ),
                            }
                        ],
                    }
                }
            )
        )
        disabled = self.run_script("install")
        self.assertIn("enabled: false", disabled.stdout)

        # 4. Invalid UTF-8 bytes emit invalid UTF-8 warning without crashing or leaking bytes
        agy_hooks.write_bytes(b"\xff\xfe\x00RAW_SECRET_BYTES")
        bad_utf8 = self.run_script("install")
        self.assertIn("invalid UTF-8 encoding", bad_utf8.stdout)
        self.assertNotIn("RAW_SECRET_BYTES", bad_utf8.stdout)
        agy_hooks.unlink()

        # 5. Foreign checkout enforce in Codex + owned audit in Claude + missing Antigravity
        #    preserves Codex=enforce when executing the suggested repair command
        foreign_script = self.base / "foreign_repo/skills/apply-conversation-lessons/scripts/encounter_ledger.py"
        foreign_script.parent.mkdir(parents=True)
        foreign_script.write_text("# foreign\n")
        (self.home / ".codex/hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": (
                                            f"python3 '{foreign_script}' hook --agent codex"
                                            " --mode enforce --installation-id secquoia-encounter-ledger"
                                        ),
                                    }
                                ]
                            }
                        ]
                    }
                }
            )
        )
        foreign = self.run_script("install")
        self.assertIn("other checkout or missing runner", foreign.stdout)
        self.assertIn("--codex-hooks=enforce", foreign.stdout)
        self.assertIn("--antigravity-hooks=audit", foreign.stdout)
        foreign_match = re.search(
            r"Run (\./install\.sh .+?) to configure the remaining client\(s\)",
            foreign.stdout,
        )
        self.assertIsNotNone(foreign_match, foreign.stdout)
        foreign_tokens = shlex.split(foreign_match.group(1))
        foreign_repair = subprocess.run(
            ["bash", str(self.repo / "install.sh"), *foreign_tokens[1:]],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(foreign_repair.returncode, 0, foreign_repair.stdout + foreign_repair.stderr)
        codex_repaired = [h["command"] for h in self.hooks(self.home / ".codex/hooks.json")]
        self.assertTrue(all("--mode enforce" in c for c in codex_repaired))
        self.assertTrue(all(str(foreign_script) not in c for c in codex_repaired))
        claude_repaired = [h["command"] for h in self.hooks(self.home / ".claude/settings.json")]
        self.assertTrue(all("--mode audit" in c for c in claude_repaired))

        # 6. Owned handler sharing a file with foreign or malformed sibling handlers still warns
        owned_codex_script = self.modern / "apply-conversation-lessons/scripts/encounter_ledger.py"
        (self.home / ".codex/hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "^Bash$",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": (
                                            f"python3 '{owned_codex_script}' hook --agent codex"
                                            " --mode audit --installation-id secquoia-encounter-ledger"
                                        ),
                                    }
                                ],
                            }
                        ],
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": (
                                            f"python3 '{foreign_script}' hook --agent codex"
                                            " --mode enforce --installation-id secquoia-encounter-ledger"
                                        ),
                                    },
                                    {
                                        "type": "command",
                                        "command": "python3 'unterminated --installation-id secquoia-encounter-ledger",
                                    },
                                ]
                            }
                        ],
                    }
                }
            )
        )
        mixed_siblings = self.run_script("install")
        self.assertIn("malformed SECQUOIA hook command in Codex", mixed_siblings.stdout)
        self.assertIn("mixes this checkout's hooks (audit) with another checkout or missing runner (enforce)", mixed_siblings.stdout)
        self.assertIn("--codex-hooks=enforce", mixed_siblings.stdout)


if __name__ == "__main__":
    unittest.main()
