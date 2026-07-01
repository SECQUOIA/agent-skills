#!/usr/bin/env bash
# Remove the SECQUOIA agent skills from Codex CLI and Claude Code.
# Only removes entries that point at (or were copied from) this repo's skills.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/skills"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
TARGETS=("$CODEX_HOME/skills" "$HOME/.claude/skills")

for T in "${TARGETS[@]}"; do
  [ -d "$T" ] || continue
  echo "Removing from $T:"
  for S in "$SRC"/*/; do
    name="$(basename "$S")"
    dest="$T/$name"
    if [ -L "$dest" ]; then
      rm "$dest"; echo "  - $name (symlink)"
    elif [ -d "$dest" ]; then
      rm -rf "$dest"; echo "  - $name (copy)"
    fi
  done
done
echo "Done."
