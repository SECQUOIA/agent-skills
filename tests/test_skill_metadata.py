"""Validate metadata contracts and link integrity, without pinning workflow prose."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("skill_metadata", ROOT / "scripts/validate_skill_metadata.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "skills"
        self.skill = self.root / "sample-skill"
        self.skill.mkdir(parents=True)
        self.entry = self.skill / "SKILL.md"
        self.write_skill()

    def write_skill(self, metadata=None, body=""):
        if metadata is None:
            metadata = "name: sample-skill\ndescription: A useful example."
        self.entry.write_text(f"---\n{metadata}\n---\n{body}", encoding="utf-8")

    def test_valid_optional_fields_and_unicode_description(self):
        self.write_skill("name: sample-skill\ndescription: " + "é" * 1024
                         + "\nlicense: MIT\nallowed-tools: Bash\nmetadata:\n  purpose: example")
        self.assertEqual(validator.validate(self.root), [])

    def test_invalid_frontmatter_fails(self):
        examples = [
            "name: sample-skill\ndescription: " + "x" * 1025,
            "name: sample-skill\ndescription: [one, two]",
            "name: sample-skill\ndescription: ''",
            "name: other-skill\ndescription: Wrong name.",
            "name: Sample-Skill\ndescription: Invalid name.",
            "name: sample-skill\ndescription: Valid.\nunsupported: value",
            "name: sample-skill\ndescription: First.\ndescription: Duplicate.",
            "name: sample-skill\ndescription: [unterminated",
            "name: sample-skill\ndescription: <placeholder>",
            "name: sample-skill\ndescription: '[TODO: fill in]'",
            "- not a mapping",
        ]
        for metadata in examples:
            with self.subTest(metadata=metadata[:80]):
                self.write_skill(metadata)
                self.assertTrue(validator.validate(self.root))

    def test_missing_frontmatter_and_empty_tree_fail(self):
        self.entry.write_text("No metadata.\n")
        self.assertTrue(validator.validate(self.root))
        self.entry.unlink()
        self.assertTrue(validator.validate(self.root))

    def test_sidecar_invocation_and_boolean_policy(self):
        sidecar = self.skill / "agents/openai.yaml"
        sidecar.parent.mkdir()
        valid = ('interface:\n  short_description: "An example skill for validation"\n'
                 '  default_prompt: "Use $sample-skill for this example."\n'
                 'policy:\n  allow_implicit_invocation: false\n')
        sidecar.write_text(valid)
        self.assertEqual(validator.validate(self.root), [])
        for invalid in (valid.replace("$sample-skill", "$sample-skill-extra"),
                        valid.replace("false", '"false"'),
                        valid + "unrecognized: true\n", "interface: [not, mapping]\n"):
            with self.subTest(sidecar=invalid):
                sidecar.write_text(invalid)
                self.assertTrue(validator.validate(self.root))

    def test_sibling_reference_and_angle_paths(self):
        sibling = self.root / "shared"
        sibling.mkdir()
        (sibling / "read me.md").write_text("Shared guidance.\n")
        self.write_skill(body='[shared](<../shared/read me.md#heading>)\n'
                              '[encoded](../shared/read%20me.md "Useful title")\n'
                              '[use reference][guide]\n[guide]: <../shared/read me.md>\n')
        self.assertEqual(validator.validate(self.root), [])
        (sibling / "read me.md").unlink()
        errors = validator.validate(self.root)
        self.assertEqual(sum("missing local link" in item for item in errors), 3)

    def test_missing_links_in_reference_documents_are_checked(self):
        refs = self.skill / "references"
        refs.mkdir()
        (refs / "details.md").write_text("[more](absent.md)\n")
        self.write_skill(body="[details](references/details.md)\n")
        self.assertTrue(any("absent.md" in error for error in validator.validate(self.root)))

    def test_code_comments_external_urls_and_anchors_are_ignored(self):
        self.write_skill(body='```markdown\n[example](missing-fenced.md)\n```\n'
                              '~~~\n[example](missing-tilde.md)\n~~~\n'
                              '`[example](missing-inline.md)`\n'
                              '    [example](missing-indented.md)\n'
                              '<!-- [example](missing-comment.md) -->\n'
                              '[web](https://example.invalid/docs) [anchor](#section)\n'
                              '[email](mailto:someone@example.invalid)\n')
        self.assertEqual(validator.validate(self.root), [])

    def test_outside_targets_and_symlinks_fail_without_reading_private_files(self):
        private = self.root.parent / "skills-local"
        private.mkdir()
        # Invalid bytes prove that validation does not parse this excluded content.
        (private / "private.md").write_bytes(b"\xff")
        self.write_skill(body="[outside](../../skills-local/private.md)\n")
        self.assertTrue(any("leaves public skills" in e for e in validator.validate(self.root)))
        self.write_skill()
        (self.skill / "linked.md").symlink_to(private / "private.md")
        self.assertTrue(any("leaves public skills" in e for e in validator.validate(self.root)))

    def test_literal_html_markers_do_not_hide_links_between_them(self):
        self.write_skill(body='Use `<!-- marker:first -->` here.\n\n'
                              '[real link](missing.md)\n\n'
                              'Another `<!-- marker:second -->` here.\n')
        self.assertTrue(any("missing.md" in e for e in validator.validate(self.root)))

    def test_cli_exit_status(self):
        command = [sys.executable, str(ROOT / "scripts/validate_skill_metadata.py"), str(self.root)]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.write_skill(body="[missing](missing.md)\n")
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)

    def test_repository_public_skills(self):
        self.assertEqual(validator.validate(ROOT / "skills"), [])


if __name__ == "__main__":
    unittest.main()
