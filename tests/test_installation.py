from __future__ import annotations

import json
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


if __name__ == "__main__":
    unittest.main()
