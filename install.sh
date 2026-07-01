#!/usr/bin/env bash
# Install the SECQUOIA agent skills into both Codex CLI and Claude Code.
#
# Usage:
#   ./install.sh            # symlink each skill into both tools (recommended; `git pull` then updates both)
#   ./install.sh --copy     # copy instead of symlink (use on Windows without symlink support)
#
# The skills reference each other by relative sibling paths, so they must be
# installed together. This script installs the whole set into each tool's skills dir.
set -euo pipefail

MODE="symlink"
[ "${1:-}" = "--copy" ] && MODE="copy"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/skills"

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
TARGETS=("$CODEX_HOME/skills" "$HOME/.claude/skills")

for T in "${TARGETS[@]}"; do
  mkdir -p "$T"
  echo "Installing into $T ($MODE):"
  for S in "$SRC"/*/; do
    name="$(basename "$S")"
    dest="$T/$name"
    if [ -L "$dest" ]; then
      rm "$dest"
    elif [ -e "$dest" ]; then
      backup="$dest.bak.$(date +%s)"
      mv "$dest" "$backup"
      echo "  ! existing $name backed up to $(basename "$backup")"
    fi
    if [ "$MODE" = "copy" ]; then
      cp -R "$S" "$dest"
    else
      ln -s "${S%/}" "$dest"
    fi
    echo "  + $name"
  done
done

echo
echo "Done. Start a fresh Codex/Claude session to pick up the skills."
echo "Update later with: git -C \"$REPO_DIR\" pull"
