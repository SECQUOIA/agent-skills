#!/usr/bin/env python3
"""Validate public skill metadata and local documentation links without execution.

Run from any directory: python scripts/validate_skill_metadata.py [skills-root].
Install validation dependencies with python -m pip install -r requirements-dev.txt.
Only immediate public skill directories are inspected; skills-local is never read.
Link checks cover inline links, images, and reference definitions outside code and
HTML comments. They verify local files, not Markdown heading anchors or web URLs.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import yaml


# The supported fields from skill-creator's quick_validate.py, shared by this set.
FRONTMATTER_KEYS = {"name", "description", "license", "allowed-tools", "metadata"}
SIDECAR_KEYS = {"interface", "dependencies", "policy"}
INTERFACE_KEYS = {
    "display_name", "short_description", "default_prompt", "icon_small",
    "icon_large", "brand_color",
}
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.S)
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
DESTINATION = r'(?:<([^>\n]*)>|((?:\\.|[^\s()\\]|\([^()\n]*\))+))'
INLINE_LINK = re.compile(
    r'(?<!\\)\[[^\]\n]*\]\(\s*' + DESTINATION
    + r'''(?:\s+(?:"[^"\n]*"|'[^'\n]*'|\([^\n)]*\)))?\s*\)'''
)
REFERENCE = re.compile(r"^[ ]{0,3}\[[^\]\n]+\]:\s*" + DESTINATION, re.M)


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject accidental duplicate keys instead of silently keeping the last."""

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise yaml.constructor.ConstructorError(
                    None, None, "metadata keys must be strings", key_node.start_mark
                )
            if key in result:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key: {key}", key_node.start_mark
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def mapping(text: str, path: Path, errors: list[str]) -> dict | None:
    try:
        value = yaml.load(text, Loader=UniqueKeyLoader)
    except yaml.YAMLError as error:
        errors.append(f"{path}: invalid YAML: {error}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path}: metadata must be a YAML mapping")
        return None
    return value


def unknown_keys(value: dict, allowed: set[str], path: Path, errors: list[str]):
    extra = sorted(value.keys() - allowed)
    if extra:
        errors.append(f"{path}: unsupported metadata keys: {', '.join(extra)}")


def validate_frontmatter(path: Path, text: str, errors: list[str]) -> None:
    match = FRONTMATTER.match(text)
    if not match:
        errors.append(f"{path}: missing or malformed YAML frontmatter")
        return
    value = mapping(match[1], path, errors)
    if value is None:
        return
    unknown_keys(value, FRONTMATTER_KEYS, path, errors)
    name = value.get("name")
    if not isinstance(name, str) or not NAME.fullmatch(name) or len(name) > 64:
        errors.append(f"{path}: name must be 1–64 lowercase hyphen-case characters")
    elif name != path.parent.name:
        errors.append(f"{path}: name must match its skill directory")
    description = value.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{path}: description must be a nonempty string")
    elif len(description) > 1024:
        errors.append(f"{path}: description exceeds 1024 characters")
    elif "<" in description or ">" in description:
        errors.append(f"{path}: description cannot contain angle brackets")
    elif description.lstrip().startswith("[TODO:"):
        errors.append(f"{path}: description contains an unfinished placeholder")


def validate_sidecar(path: Path, text: str, errors: list[str]) -> None:
    value = mapping(text, path, errors)
    if value is None:
        return
    unknown_keys(value, SIDECAR_KEYS, path, errors)
    for key in SIDECAR_KEYS & value.keys():
        if not isinstance(value[key], dict):
            errors.append(f"{path}: {key} must be a mapping")
    interface = value.get("interface", {})
    if isinstance(interface, dict):
        unknown_keys(interface, INTERFACE_KEYS, path, errors)
        for key, item in interface.items():
            if not isinstance(item, str) or not item.strip():
                errors.append(f"{path}: interface.{key} must be a nonempty string")
        short = interface.get("short_description")
        if isinstance(short, str) and not 25 <= len(short) <= 64:
            errors.append(f"{path}: short_description must contain 25–64 characters")
        prompt = interface.get("default_prompt")
        name = path.parent.parent.name
        if isinstance(prompt, str) and not re.search(r"\$" + re.escape(name) + r"(?![a-z0-9-])", prompt):
            errors.append(f"{path}: default_prompt must mention ${name}")
    policy = value.get("policy", {})
    if isinstance(policy, dict):
        unknown_keys(policy, {"allow_implicit_invocation"}, path, errors)
        if "allow_implicit_invocation" in policy and not isinstance(policy["allow_implicit_invocation"], bool):
            errors.append(f"{path}: allow_implicit_invocation must be a boolean")


def prose(text: str) -> str:
    """Remove comments and code examples before extracting document links."""
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^[ \t]*(?:[-+*] )?(`{3,}|~{3,})(.*)$", line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if fence is None and not line.startswith(("    ", "\t")):
            lines.append(line)
    # Match code spans before HTML comments within them. Removing the comment
    # first would manufacture adjacent backticks and swallow intervening prose.
    return re.sub(r"(`+)([^`]|(?!\1)`)*?\1|<!--[\s\S]*?-->", "", "\n".join(lines))


def link_destinations(text: str):
    text = prose(text)
    for expression in (INLINE_LINK, REFERENCE):
        for match in expression.finditer(text):
            yield match[1] if match[1] is not None else match[2]


def validate_links(path: Path, text: str, root: Path, errors: list[str]) -> None:
    for destination in link_destinations(text):
        destination = re.sub(r"\\([\\() ])", r"\1", destination)
        try:
            parsed = urlsplit(destination)
        except ValueError:
            errors.append(f"{path}: malformed link: {destination}")
            continue
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        target = (path.parent / unquote(parsed.path)).resolve()
        if not target.is_relative_to(root):
            errors.append(f"{path}: local link leaves public skills: {destination}")
        elif not target.exists():
            errors.append(f"{path}: missing local link target: {destination}")


def validate(root: Path) -> list[str]:
    root = root.resolve()
    errors = []
    entries = sorted(root.glob("*/SKILL.md"))
    if not entries:
        return [f"{root}: no public skill entrypoints found"]
    for entry in entries:
        if not entry.resolve().is_relative_to(root):
            errors.append(f"{entry}: skill entrypoint leaves public skills")
            continue
        for path in sorted(entry.parent.rglob("*.md")):
            if not path.resolve().is_relative_to(root):
                errors.append(f"{path}: documentation leaves public skills")
                continue
            text = path.read_text(encoding="utf-8")
            if path == entry:
                validate_frontmatter(path, text, errors)
            validate_links(path, text, root, errors)
        sidecar = entry.parent / "agents/openai.yaml"
        if sidecar.is_file():
            if not sidecar.resolve().is_relative_to(root):
                errors.append(f"{sidecar}: sidecar leaves public skills")
            else:
                validate_sidecar(sidecar, sidecar.read_text(encoding="utf-8"), errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skills_root", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "skills")
    args = parser.parse_args()
    errors = validate(args.skills_root)
    if errors:
        print("\n".join(errors))
        return 1
    print("Public skill metadata and local links are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
